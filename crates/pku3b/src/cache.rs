//! Cache metadata, typed cache storage, and artifact cache helpers.
//!
//! pku3b is invoked like a live access layer by PkuClaw. Each CLI execution
//! performs cache-first lookup, optional network refresh, stale fallback, and
//! reports provenance in the JSON envelope `meta.cache` field.

use std::{
    fmt,
    path::{Path, PathBuf},
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use anyhow::Context as _;
use compio::{buf::buf_try, fs};
use serde::{Deserialize, Serialize, de::DeserializeOwned};

use crate::utils;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
#[allow(dead_code)]
pub enum CacheMode {
    Hit,
    Miss,
    Refresh,
    Bypass,
    Disabled,
    Stale,
    Mixed,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CacheKind {
    Metadata,
    Artifact,
    Mixed,
    None,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct CacheSummary {
    pub hits: u64,
    pub misses: u64,
    pub refreshes: u64,
    pub stale_hits: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct CacheMeta {
    pub mode: CacheMode,
    pub kind: CacheKind,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ttl_seconds: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expires_at: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub key: Option<String>,
    pub stale: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub summary: Option<CacheSummary>,
}

impl CacheMeta {
    pub fn disabled() -> Self {
        Self {
            mode: CacheMode::Disabled,
            kind: CacheKind::None,
            ttl_seconds: None,
            expires_at: None,
            key: None,
            stale: false,
            summary: None,
        }
    }

    pub fn artifact(mode: CacheMode, key: impl Into<String>) -> Self {
        Self {
            mode,
            kind: CacheKind::Artifact,
            ttl_seconds: None,
            expires_at: None,
            key: Some(key.into()),
            stale: false,
            summary: None,
        }
    }

    fn metadata(
        mode: CacheMode,
        key: &str,
        ttl: Duration,
        created_at_unix: u64,
        stale: bool,
    ) -> Self {
        let expires = created_at_unix.saturating_add(ttl.as_secs());
        Self {
            mode,
            kind: CacheKind::Metadata,
            ttl_seconds: Some(ttl.as_secs()),
            expires_at: Some(format_unix(expires)),
            key: Some(key.to_owned()),
            stale,
            summary: None,
        }
    }
}

#[derive(Debug, Clone)]
pub struct Cached<T> {
    pub data: T,
    pub meta: CacheMeta,
    pub warnings: Vec<String>,
}

impl<T> Cached<T> {
    fn new(data: T, meta: CacheMeta) -> Self {
        Self {
            data,
            meta,
            warnings: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct MetadataFile<T> {
    schema_version: u32,
    key: String,
    created_at_unix: u64,
    generated_at: String,
    ttl_seconds: u64,
    data: T,
}

pub fn metadata_dir() -> PathBuf {
    utils::projectdir().cache_dir().join("metadata")
}

pub fn artifact_dir() -> PathBuf {
    utils::projectdir().cache_dir().join("artifact")
}

pub fn legacy_dir() -> PathBuf {
    utils::projectdir().cache_dir().to_path_buf()
}

pub fn metadata_path(key: &str) -> PathBuf {
    metadata_dir().join(format!("{}.json", safe_component(key)))
}

pub fn artifact_path(key: &str, filename: &str) -> PathBuf {
    artifact_dir()
        .join(safe_component(key))
        .join(safe_filename(filename))
}

pub async fn metadata_json<T, Fut, F>(
    key: impl Into<String>,
    ttl: Duration,
    refresh: bool,
    fetch: F,
) -> anyhow::Result<Cached<T>>
where
    T: Serialize + DeserializeOwned + Clone + 'static,
    Fut: std::future::Future<Output = anyhow::Result<T>>,
    F: FnOnce() -> Fut,
{
    let key = key.into();
    let path = metadata_path(&key);
    let existing = read_metadata::<T>(&path).await.ok();
    let now = unix_now();

    if !refresh
        && let Some(file) = &existing
        && file.key == key
        && now < file.created_at_unix.saturating_add(ttl.as_secs())
    {
        return Ok(Cached::new(
            file.data.clone(),
            CacheMeta::metadata(CacheMode::Hit, &key, ttl, file.created_at_unix, false),
        ));
    }

    let had_existing = existing.is_some();
    match fetch().await {
        Ok(data) => {
            let created_at_unix = unix_now();
            let file = MetadataFile {
                schema_version: 1,
                key: key.clone(),
                created_at_unix,
                generated_at: chrono::Local::now().to_rfc3339(),
                ttl_seconds: ttl.as_secs(),
                data: data.clone(),
            };
            write_metadata(&path, &file).await?;
            let mode = if refresh || had_existing {
                CacheMode::Refresh
            } else {
                CacheMode::Miss
            };
            Ok(Cached::new(
                data,
                CacheMeta::metadata(mode, &key, ttl, created_at_unix, false),
            ))
        }
        Err(err) => {
            if let Some(file) = existing {
                let mut cached = Cached::new(
                    file.data,
                    CacheMeta::metadata(CacheMode::Stale, &key, ttl, file.created_at_unix, true),
                );
                cached.warnings.push(format!(
                    "network refresh failed; returned stale metadata cache for key {key}: {err:#}"
                ));
                Ok(cached)
            } else {
                Err(err)
            }
        }
    }
}

async fn read_metadata<T: DeserializeOwned>(path: &Path) -> anyhow::Result<MetadataFile<T>> {
    let buf = fs::read(path).await?;
    serde_json::from_slice(&buf).with_context(|| format!("parse metadata cache {}", path.display()))
}

async fn write_metadata<T: Serialize>(path: &Path, file: &MetadataFile<T>) -> anyhow::Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).await?;
    }
    let tmp = path.with_extension("json.tmp");
    let bytes = serde_json::to_vec(file)?;
    buf_try!(@try fs::write(&tmp, bytes).await);
    fs::rename(tmp, path).await?;
    Ok(())
}

#[derive(Debug, Clone, Serialize)]
pub struct ArtifactResult {
    pub name: String,
    pub path: PathBuf,
    pub cache_hit: bool,
    pub downloaded: bool,
    pub bytes: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub checksum: Option<String>,
}

#[derive(Debug, Clone)]
pub struct ArtifactCached {
    pub file: ArtifactResult,
    pub meta: CacheMeta,
    pub warnings: Vec<String>,
}

pub async fn materialize_artifact<Fut, F>(
    key: &str,
    filename: &str,
    out_dir: &Path,
    refresh: bool,
    download: F,
) -> anyhow::Result<ArtifactCached>
where
    Fut: std::future::Future<Output = anyhow::Result<bytes::Bytes>>,
    F: FnOnce() -> Fut,
{
    fs::create_dir_all(out_dir).await?;
    let safe_name = safe_filename(filename);
    let dest = out_dir.join(&safe_name);

    if !refresh && complete_file(&dest) {
        let bytes = std::fs::metadata(&dest)?.len();
        return Ok(ArtifactCached {
            file: ArtifactResult {
                name: safe_name,
                path: dest,
                cache_hit: true,
                downloaded: false,
                bytes,
                checksum: None,
            },
            meta: CacheMeta::artifact(CacheMode::Hit, key),
            warnings: Vec::new(),
        });
    }

    let cache_path = artifact_path(key, &safe_name);
    if !refresh && complete_file(&cache_path) {
        copy_or_hardlink(&cache_path, &dest).await?;
        let bytes = std::fs::metadata(&dest)?.len();
        return Ok(ArtifactCached {
            file: ArtifactResult {
                name: safe_name,
                path: dest,
                cache_hit: true,
                downloaded: false,
                bytes,
                checksum: None,
            },
            meta: CacheMeta::artifact(CacheMode::Hit, key),
            warnings: Vec::new(),
        });
    }

    let bytes = download().await?;
    anyhow::ensure!(!bytes.is_empty(), "downloaded artifact is empty");
    if let Some(parent) = cache_path.parent() {
        fs::create_dir_all(parent).await?;
    }
    let tmp = cache_path.with_extension("tmp");
    buf_try!(@try fs::write(&tmp, bytes.clone()).await);
    fs::rename(tmp, &cache_path).await?;
    copy_or_hardlink(&cache_path, &dest).await?;
    let len = std::fs::metadata(&dest)?.len();
    Ok(ArtifactCached {
        file: ArtifactResult {
            name: safe_name,
            path: dest,
            cache_hit: false,
            downloaded: true,
            bytes: len,
            checksum: None,
        },
        meta: CacheMeta::artifact(
            if refresh {
                CacheMode::Refresh
            } else {
                CacheMode::Miss
            },
            key,
        ),
        warnings: Vec::new(),
    })
}

fn complete_file(path: &Path) -> bool {
    std::fs::metadata(path)
        .map(|m| m.is_file() && m.len() > 0)
        .unwrap_or(false)
}

async fn copy_or_hardlink(src: &Path, dest: &Path) -> anyhow::Result<()> {
    if let Some(parent) = dest.parent() {
        fs::create_dir_all(parent).await?;
    }
    if dest.exists() {
        std::fs::remove_file(dest)?;
    }
    match std::fs::hard_link(src, dest) {
        Ok(()) => Ok(()),
        Err(_) => {
            std::fs::copy(src, dest)?;
            Ok(())
        }
    }
}

pub fn stats(dir: &Path) -> anyhow::Result<(u64, u64)> {
    fn walk(path: &Path, files: &mut u64, bytes: &mut u64) -> anyhow::Result<()> {
        if !path.exists() {
            return Ok(());
        }
        for entry in std::fs::read_dir(path)? {
            let entry = entry?;
            let meta = entry.metadata()?;
            if meta.is_dir() {
                walk(&entry.path(), files, bytes)?;
            } else if meta.is_file() {
                *files += 1;
                *bytes += meta.len();
            }
        }
        Ok(())
    }
    let mut files = 0;
    let mut bytes = 0;
    walk(dir, &mut files, &mut bytes)?;
    Ok((files, bytes))
}

pub async fn clean_kind(kind: CleanKind) -> anyhow::Result<(u64, u64)> {
    let dirs = match kind {
        CleanKind::Metadata => vec![metadata_dir()],
        CleanKind::Artifact => vec![artifact_dir()],
        CleanKind::All => vec![metadata_dir(), artifact_dir()],
    };
    let mut files = 0;
    let mut bytes = 0;
    for dir in dirs {
        let (f, b) = stats(&dir)?;
        files += f;
        bytes += b;
        if dir.exists() {
            std::fs::remove_dir_all(&dir)?;
        }
    }
    Ok((files, bytes))
}

#[derive(Debug, Clone, Copy)]
pub enum CleanKind {
    Metadata,
    Artifact,
    All,
}

pub fn safe_component(value: &str) -> String {
    let mut out = String::new();
    for ch in value.chars() {
        match ch {
            'a'..='z' | 'A'..='Z' | '0'..='9' | '-' | '_' | '.' => out.push(ch),
            ':' => out.push_str("__"),
            _ => out.push('_'),
        }
    }
    if out.is_empty() { "_".to_owned() } else { out }
}

pub fn safe_filename(value: &str) -> String {
    let value = value.trim().trim_matches('\u{a0}');
    let mut out = String::new();
    for ch in value.chars() {
        match ch {
            '/' | '\\' | ':' | '*' | '?' | '"' | '<' | '>' | '|' | '\0' => out.push('_'),
            _ => out.push(ch),
        }
    }
    let out = out.trim();
    if out.is_empty() {
        "download.bin".to_owned()
    } else {
        out.to_owned()
    }
}

fn unix_now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

fn format_unix(secs: u64) -> String {
    chrono::DateTime::<chrono::Utc>::from_timestamp(secs as i64, 0)
        .unwrap_or_else(chrono::Utc::now)
        .with_timezone(&chrono::Local)
        .to_rfc3339()
}

impl fmt::Display for CacheMode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{}",
            serde_json::to_value(self)
                .unwrap_or_default()
                .as_str()
                .unwrap_or("unknown")
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cache_meta_serializes_expected_fields() {
        let meta = CacheMeta::metadata(
            CacheMode::Hit,
            "courses:list:current",
            Duration::from_secs(900),
            1_700_000_000,
            false,
        );
        let value = serde_json::to_value(meta).unwrap();
        assert_eq!(value["mode"], "hit");
        assert_eq!(value["kind"], "metadata");
        assert_eq!(value["ttl_seconds"], 900);
        assert_eq!(value["key"], "courses:list:current");
        assert_eq!(value["stale"], false);
    }

    #[test]
    fn artifact_result_serializes_contract_fields() {
        let result = ArtifactResult {
            name: "lecture.pdf".to_owned(),
            path: PathBuf::from("/tmp/lecture.pdf"),
            cache_hit: true,
            downloaded: false,
            bytes: 12345,
            checksum: None,
        };
        let value = serde_json::to_value(result).unwrap();
        assert_eq!(value["name"], "lecture.pdf");
        assert_eq!(value["cache_hit"], true);
        assert_eq!(value["downloaded"], false);
        assert_eq!(value["bytes"], 12345);
    }

    #[test]
    fn safe_filename_removes_path_separators() {
        assert_eq!(safe_filename("a/b:c?.pdf"), "a_b_c_.pdf");
    }
}
