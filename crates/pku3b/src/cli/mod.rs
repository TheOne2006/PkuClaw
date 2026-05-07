mod output;

use crate::api::blackboard::*;
use crate::{api, build, cache, config, id, utils};
use anyhow::{Context as _, bail};
use clap::{Parser, Subcommand, ValueEnum};
use compio::{buf::buf_try, fs, io::AsyncWrite};
use futures_util::future::try_join_all;
use serde::Serialize;
use serde_json::json;
use std::{path::PathBuf, sync::Arc, time::Duration};

pub use output::{CommandOutcome, anyhow_to_error, clap_error_to_error, exit_code, print_error};

#[derive(Parser)]
#[command(
    version,
    long_version(shadow_rs::formatcp!(
        "{}\nbuild_time: {}\nbuild_env: {}, {}\nbuild_target: {} (on {})",
        build::PKG_VERSION, build::BUILD_TIME, build::RUST_VERSION, build::RUST_CHANNEL,
        build::BUILD_TARGET, build::BUILD_OS
    )),
    author,
    about = "Raw JSON CLI for PKU Blackboard data"
)]
pub struct Cli {
    /// Pretty-print JSON output.
    #[arg(long, global = true, default_value_t = false)]
    pretty: bool,

    /// Bypass pku3b typed caches for supported commands.
    #[arg(long, global = true, default_value_t = false)]
    refresh: bool,

    #[command(subcommand)]
    command: Commands,
}

impl Cli {
    pub fn pretty(&self) -> bool {
        self.pretty
    }
}

#[derive(Subcommand)]
enum Commands {
    Auth(AuthCommand),
    Config(ConfigCommand),
    Cache(CacheCommand),
    Courses(CoursesCommand),
    Courseware(CoursewareCommand),
    Explore(ExploreCommand),
    Assignments(AssignmentsCommand),
    Announcements(AnnouncementsCommand),
    Timetable(TimetableCommand),
    Videos(VideosCommand),
}

#[derive(clap::Args)]
struct AuthCommand {
    #[command(subcommand)]
    command: AuthCommands,
}

#[derive(Subcommand)]
enum AuthCommands {
    Login {
        #[arg(long)]
        username: String,
        #[arg(long)]
        password: String,
        #[arg(long, default_value = "")]
        otp: String,
    },
    Status,
    Logout,
}

#[derive(clap::Args)]
struct ConfigCommand {
    #[command(subcommand)]
    command: ConfigCommands,
}

#[derive(Subcommand)]
enum ConfigCommands {
    Get { key: Option<ConfigKey> },
    Set { key: ConfigKey, value: String },
}

#[derive(Debug, Clone, ValueEnum)]
enum ConfigKey {
    Username,
    Password,
}

#[derive(clap::Args)]
struct CacheCommand {
    #[command(subcommand)]
    command: CacheCommands,
}

#[derive(Subcommand)]
enum CacheCommands {
    Status,
    Clean {
        #[arg(long, value_enum, default_value_t = CacheCleanKind::All)]
        kind: CacheCleanKind,
    },
}

#[derive(Debug, Clone, Copy, ValueEnum)]
enum CacheCleanKind {
    Metadata,
    Artifact,
    All,
}

#[derive(clap::Args)]
struct CoursesCommand {
    #[command(subcommand)]
    command: CoursesCommands,
}

#[derive(Subcommand)]
enum CoursesCommands {
    List {
        #[arg(long, value_enum, default_value_t = Term::Current)]
        term: Term,
    },
    Contents {
        #[arg(long)]
        id: String,
        #[arg(long)]
        root_content_id: Option<String>,
    },
    Grades {
        #[arg(long)]
        id: String,
    },
}

#[derive(clap::Args)]
struct CoursewareCommand {
    #[command(subcommand)]
    command: CoursewareCommands,
}

#[derive(Subcommand)]
enum CoursewareCommands {
    List {
        #[arg(long)]
        course_id: String,
    },
    Download {
        #[arg(long)]
        id: String,
        #[arg(long)]
        out_dir: PathBuf,
    },
}

#[derive(clap::Args)]
struct ExploreCommand {
    #[command(subcommand)]
    command: ExploreCommands,
}

#[derive(Subcommand)]
enum ExploreCommands {
    Visit {
        #[arg(long)]
        url: String,
        #[arg(long, default_value_t = 20_000)]
        max_chars: usize,
        #[arg(long, default_value_t = 200)]
        max_links: usize,
        #[arg(long, default_value_t = 100)]
        max_table_rows: usize,
    },
}

#[derive(clap::Args)]
struct AssignmentsCommand {
    #[command(subcommand)]
    command: AssignmentsCommands,
}

#[derive(Subcommand)]
enum AssignmentsCommands {
    List {
        #[arg(long, value_enum, default_value_t = Term::Current)]
        term: Term,
    },
    Get {
        #[arg(long)]
        id: String,
        #[arg(long, value_enum, default_value_t = Term::Current)]
        term: Term,
    },
    Download {
        #[arg(long)]
        id: String,
        #[arg(long)]
        out_dir: PathBuf,
        #[arg(long, value_enum, default_value_t = Term::Current)]
        term: Term,
    },
    DownloadSubmission {
        #[arg(long)]
        id: String,
        #[arg(long)]
        out_dir: PathBuf,
        #[arg(long, value_enum, default_value_t = Term::Current)]
        term: Term,
    },
    Submit {
        #[arg(long)]
        id: String,
        #[arg(long)]
        file: PathBuf,
    },
}

#[derive(clap::Args)]
struct AnnouncementsCommand {
    #[command(subcommand)]
    command: AnnouncementsCommands,
}

#[derive(Subcommand)]
enum AnnouncementsCommands {
    List {
        #[arg(long, value_enum, default_value_t = Term::Current)]
        term: Term,
    },
    Get {
        #[arg(long)]
        id: String,
        #[arg(long, value_enum, default_value_t = Term::Current)]
        term: Term,
    },
}

#[derive(clap::Args)]
struct TimetableCommand {
    #[command(subcommand)]
    command: TimetableCommands,
}

#[derive(Subcommand)]
enum TimetableCommands {
    Get,
}

#[derive(clap::Args)]
struct VideosCommand {
    #[command(subcommand)]
    command: VideosCommands,
}

#[derive(Subcommand)]
enum VideosCommands {
    List {
        #[arg(long, value_enum, default_value_t = Term::Current)]
        term: Term,
    },
    Download {
        #[arg(long)]
        id: String,
        #[arg(long)]
        out_dir: PathBuf,
        #[arg(long, value_enum, default_value_t = Term::Current)]
        term: Term,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, ValueEnum, Serialize)]
#[serde(rename_all = "snake_case")]
enum Term {
    Current,
    All,
}

impl Term {
    fn only_current(self) -> bool {
        self == Self::Current
    }

    fn as_str(self) -> &'static str {
        match self {
            Self::Current => "current",
            Self::All => "all",
        }
    }
}

#[derive(Debug, Serialize)]
struct CourseJson {
    id: String,
    title: String,
    name: String,
    is_current: bool,
    launcher_url: String,
}

impl From<&CourseMeta> for CourseJson {
    fn from(meta: &CourseMeta) -> Self {
        Self {
            id: meta.id().to_owned(),
            title: meta.title().to_owned(),
            name: meta.name().to_owned(),
            is_current: meta.is_current(),
            launcher_url: meta.launcher_url().to_owned(),
        }
    }
}

#[derive(Debug, Serialize)]
struct AttachmentJson {
    name: String,
    url: String,
}

#[derive(Debug, Serialize)]
struct AssignmentJson {
    id: String,
    course: CourseJson,
    title: String,
    descriptions: Vec<String>,
    attachments: Vec<AttachmentJson>,
    deadline_raw: Option<String>,
    deadline: Option<String>,
    last_attempt: Option<String>,
    submitted: bool,
    submission_summary: CourseAssignmentSubmissionSummary,
}

#[derive(Debug, Serialize)]
struct AnnouncementJson {
    id: String,
    course: CourseJson,
    title: String,
    time_raw: Option<String>,
    descriptions: Vec<String>,
    attachments: Vec<AttachmentJson>,
}

#[derive(Debug, Serialize)]
struct VideoJson {
    id: String,
    course: CourseJson,
    title: String,
    time_raw: String,
}

pub async fn start(cli: Cli) -> anyhow::Result<()> {
    let pretty = cli.pretty;
    let refresh = cli.refresh;
    let outcome = match cli.command {
        Commands::Auth(cmd) => run_auth(cmd).await?,
        Commands::Config(cmd) => run_config(cmd).await?,
        Commands::Cache(cmd) => run_cache(cmd).await?,
        Commands::Courses(cmd) => run_courses(cmd, refresh).await?,
        Commands::Courseware(cmd) => run_courseware(cmd, refresh).await?,
        Commands::Explore(cmd) => run_explore(cmd, refresh).await?,
        Commands::Assignments(cmd) => run_assignments(cmd, refresh).await?,
        Commands::Announcements(cmd) => run_announcements(cmd, refresh).await?,
        Commands::Timetable(cmd) => run_timetable(cmd, refresh).await?,
        Commands::Videos(cmd) => run_videos(cmd, refresh).await?,
    };
    output::print_ok(outcome, pretty)
}

async fn run_auth(cmd: AuthCommand) -> anyhow::Result<CommandOutcome> {
    match cmd.command {
        AuthCommands::Login {
            username,
            password,
            otp,
        } => {
            let cfg = config::Config { username, password };
            let cfg_path = utils::default_config_path();
            config::write_cfg(&cfg_path, &cfg).await?;

            let client = build_client(false).await?;
            client
                .blackboard(&cfg.username, &cfg.password, &otp)
                .await
                .context("login to blackboard")?;
            let portal_login = client.portal(&cfg.username, &cfg.password, &otp).await;
            if let Err(err) = &portal_login {
                log::warn!("portal login failed during auth login: {err:#}");
            }
            client.save_cookies().await?;

            Ok(CommandOutcome::new(json!({
                "config_path": cfg_path,
                "cookie_path": utils::default_user_agent_data_path(),
                "username": cfg.username,
                "blackboard_authenticated": true,
                "portal_authenticated": portal_login.is_ok(),
            })))
        }
        AuthCommands::Status => {
            let cfg_path = utils::default_config_path();
            let cookie_path = utils::default_user_agent_data_path();
            let config_present = cfg_path.exists();
            let cookie_present = cookie_path.exists();
            let username = config::read_cfg(&cfg_path)
                .await
                .ok()
                .map(|cfg| cfg.username);
            let client = build_client(true).await?;
            let blackboard_authenticated = client.bb_homepage().await.is_ok();
            Ok(CommandOutcome::new(json!({
                "config_present": config_present,
                "cookie_present": cookie_present,
                "username": username,
                "blackboard_authenticated": blackboard_authenticated,
                "config_path": cfg_path,
                "cookie_path": cookie_path,
            })))
        }
        AuthCommands::Logout => {
            let cookie_path = utils::default_user_agent_data_path();
            let removed = if cookie_path.exists() {
                fs::remove_file(&cookie_path).await?;
                true
            } else {
                false
            };
            Ok(CommandOutcome::new(json!({
                "cookie_path": cookie_path,
                "removed": removed,
            })))
        }
    }
}

async fn run_config(cmd: ConfigCommand) -> anyhow::Result<CommandOutcome> {
    let cfg_path = utils::default_config_path();
    match cmd.command {
        ConfigCommands::Get { key } => {
            let cfg = config::read_cfg(&cfg_path).await.context("read config")?;
            let data = match key {
                Some(ConfigKey::Username) => json!({"username": cfg.username}),
                Some(ConfigKey::Password) => json!({"password": cfg.password}),
                None => serde_json::to_value(&cfg)?,
            };
            Ok(CommandOutcome::new(
                json!({"config_path": cfg_path, "config": data}),
            ))
        }
        ConfigCommands::Set { key, value } => {
            let mut cfg = config::read_cfg(&cfg_path)
                .await
                .unwrap_or_else(|_| config::Config {
                    username: String::new(),
                    password: String::new(),
                });
            match key {
                ConfigKey::Username => cfg.username = value,
                ConfigKey::Password => cfg.password = value,
            }
            config::write_cfg(&cfg_path, &cfg).await?;
            Ok(CommandOutcome::new(
                json!({"config_path": cfg_path, "updated": true}),
            ))
        }
    }
}

async fn run_cache(cmd: CacheCommand) -> anyhow::Result<CommandOutcome> {
    match cmd.command {
        CacheCommands::Status => {
            let metadata_dir = cache::metadata_dir();
            let artifact_dir = cache::artifact_dir();
            let cache_dir = cache::legacy_dir();
            let (metadata_files, metadata_bytes) = cache::stats(&metadata_dir)?;
            let (artifact_files, artifact_bytes) = cache::stats(&artifact_dir)?;
            let (total_files, total_bytes) = cache::stats(&cache_dir)?;
            Ok(CommandOutcome::new(json!({
                "cache_dir": cache_dir,
                "metadata": {"dir": metadata_dir, "files": metadata_files, "bytes": metadata_bytes},
                "artifact": {"dir": artifact_dir, "files": artifact_files, "bytes": artifact_bytes},
                "total": {"files": total_files, "bytes": total_bytes},
            })))
        }
        CacheCommands::Clean { kind } => {
            let clean_kind = match kind {
                CacheCleanKind::Metadata => cache::CleanKind::Metadata,
                CacheCleanKind::Artifact => cache::CleanKind::Artifact,
                CacheCleanKind::All => cache::CleanKind::All,
            };
            let (files, bytes) = cache::clean_kind(clean_kind).await?;
            Ok(CommandOutcome::new(json!({
                "kind": format!("{kind:?}").to_ascii_lowercase(),
                "removed_files": files,
                "removed_bytes": bytes,
            })))
        }
    }
}

async fn cached_value<Fut, F>(
    key: impl Into<String>,
    ttl: Duration,
    refresh: bool,
    fetch: F,
) -> anyhow::Result<CommandOutcome>
where
    Fut: std::future::Future<Output = anyhow::Result<serde_json::Value>>,
    F: FnOnce() -> Fut,
{
    let cached = cache::metadata_json(key, ttl, refresh, fetch).await?;
    Ok(CommandOutcome::with_cache(
        cached.data,
        cached.meta,
        cached.warnings,
    ))
}

fn metadata_ttl_short() -> Duration {
    Duration::from_secs(10 * 60)
}

fn metadata_ttl_timetable() -> Duration {
    Duration::from_secs(6 * 60 * 60)
}

fn metadata_ttl_videos() -> Duration {
    Duration::from_secs(60 * 60)
}

fn metadata_ttl_explore() -> Duration {
    Duration::from_secs(5 * 60)
}

fn mixed_cache_meta(kind: cache::CacheKind, metas: &[cache::CacheMeta]) -> cache::CacheMeta {
    let mut summary = cache::CacheSummary::default();
    let mut stale = false;
    for meta in metas {
        stale |= meta.stale;
        match meta.mode {
            cache::CacheMode::Hit => summary.hits += 1,
            cache::CacheMode::Miss => summary.misses += 1,
            cache::CacheMode::Refresh => summary.refreshes += 1,
            cache::CacheMode::Stale => summary.stale_hits += 1,
            cache::CacheMode::Mixed => {
                if let Some(s) = &meta.summary {
                    summary.hits += s.hits;
                    summary.misses += s.misses;
                    summary.refreshes += s.refreshes;
                    summary.stale_hits += s.stale_hits;
                }
            }
            cache::CacheMode::Bypass | cache::CacheMode::Disabled => {}
        }
    }
    cache::CacheMeta {
        mode: cache::CacheMode::Mixed,
        kind,
        ttl_seconds: None,
        expires_at: None,
        key: None,
        stale,
        summary: Some(summary),
    }
}

async fn courses_list_value(term: Term) -> anyhow::Result<serde_json::Value> {
    let courses = load_courses(true, term.only_current()).await?;
    let courses = courses
        .iter()
        .map(|course| CourseJson::from(course.meta()))
        .collect::<Vec<_>>();
    Ok(json!({"term": term, "courses": courses}))
}

async fn load_course_by_id(course_id: &str) -> anyhow::Result<Course> {
    let courses = load_courses(true, false).await?;
    let Some(handle) = courses
        .into_iter()
        .find(|course| course.meta().id() == course_id)
    else {
        bail!("course with id {course_id} not found");
    };
    handle.get().await.context("fetch course")
}

async fn course_contents_value(
    course_id: &str,
    root_content_id: Option<&str>,
) -> anyhow::Result<serde_json::Value> {
    let course = load_course_by_id(course_id).await?;
    let tree = course.get_contents_tree(root_content_id).await?;
    serde_json::to_value(tree).context("serialize course contents")
}

async fn courseware_list_value(course_id: &str) -> anyhow::Result<serde_json::Value> {
    let course = load_course_by_id(course_id).await?;
    let list = course.list_courseware().await?;
    serde_json::to_value(list).context("serialize courseware list")
}

async fn grades_value(course_id: &str) -> anyhow::Result<serde_json::Value> {
    let course = load_course_by_id(course_id).await?;
    let grades = course.get_grades().await?;
    serde_json::to_value(grades).context("serialize grades")
}

async fn explore_visit_value(
    url: &str,
    max_chars: usize,
    max_links: usize,
    max_table_rows: usize,
) -> anyhow::Result<serde_json::Value> {
    let cfg = read_config().await?;
    let client = build_client(false).await?;
    client
        .blackboard(&cfg.username, &cfg.password, "")
        .await
        .context("login to blackboard")?;
    client.save_cookies().await?;
    let result = client
        .explore_visit(
            url,
            api::explore::ExploreVisitOptions {
                max_chars,
                max_links,
                max_table_rows,
            },
        )
        .await?;
    serde_json::to_value(result).context("serialize explore visit")
}

async fn assignment_detail_value(id: &str, term: Term) -> anyhow::Result<serde_json::Value> {
    let items = fetch_assignments(true, true, term.only_current()).await?;
    let Some((course, _, assignment)) = items.into_iter().find(|(_, item_id, _)| item_id == id)
    else {
        bail!("assignment with id {id} not found");
    };
    let submission = assignment.get_submission().await?;
    Ok(json!({
        "assignment": assignment_json(&course, id, &assignment),
        "submission": submission,
    }))
}

#[derive(Debug, Clone)]
struct SubmittedFileIdParts {
    assignment_id: String,
    course_id: String,
    content_id: String,
    attempt_id: String,
    file_id: String,
}

fn parse_submitted_file_id(id: &str) -> anyhow::Result<SubmittedFileIdParts> {
    let (assignment_id, rest) = id
        .split_once(":attempt:")
        .ok_or_else(|| anyhow::anyhow!("invalid submitted file id {id}: missing :attempt:"))?;
    let (course_id, content_id) = assignment_id
        .split_once(':')
        .ok_or_else(|| anyhow::anyhow!("invalid assignment id in submitted file id {id}"))?;
    let (attempt_id, file_id) = rest
        .split_once(":file:")
        .ok_or_else(|| anyhow::anyhow!("invalid submitted file id {id}: missing :file:"))?;
    anyhow::ensure!(
        !attempt_id.is_empty(),
        "invalid submitted file id {id}: empty attempt id"
    );
    anyhow::ensure!(
        !file_id.is_empty(),
        "invalid submitted file id {id}: empty file id"
    );
    Ok(SubmittedFileIdParts {
        assignment_id: assignment_id.to_owned(),
        course_id: course_id.to_owned(),
        content_id: content_id.to_owned(),
        attempt_id: attempt_id.to_owned(),
        file_id: file_id.to_owned(),
    })
}

async fn run_courses(cmd: CoursesCommand, refresh: bool) -> anyhow::Result<CommandOutcome> {
    match cmd.command {
        CoursesCommands::List { term } => {
            cached_value(
                format!("courses:list:{}", term.as_str()),
                metadata_ttl_short(),
                refresh,
                || async move { courses_list_value(term).await },
            )
            .await
        }
        CoursesCommands::Contents {
            id,
            root_content_id,
        } => {
            let cache_key = format!(
                "courses:contents:{id}:{}",
                root_content_id.as_deref().unwrap_or("default")
            );
            cached_value(cache_key, metadata_ttl_short(), refresh, || async move {
                course_contents_value(&id, root_content_id.as_deref()).await
            })
            .await
        }
        CoursesCommands::Grades { id } => {
            cached_value(
                format!("courses:grades:{id}"),
                metadata_ttl_short(),
                refresh,
                || async move { grades_value(&id).await },
            )
            .await
        }
    }
}

async fn run_courseware(cmd: CoursewareCommand, refresh: bool) -> anyhow::Result<CommandOutcome> {
    match cmd.command {
        CoursewareCommands::List { course_id } => {
            cached_value(
                format!("courseware:list:{course_id}"),
                metadata_ttl_short(),
                refresh,
                || async move { courseware_list_value(&course_id).await },
            )
            .await
        }
        CoursewareCommands::Download { id, out_dir } => {
            let course_id = id
                .split(':')
                .next()
                .filter(|value| !value.is_empty())
                .ok_or_else(|| anyhow::anyhow!("invalid courseware id {id}"))?
                .to_owned();
            let list_cached = cache::metadata_json(
                format!("courseware:list:{course_id}"),
                metadata_ttl_short(),
                refresh,
                || async { courseware_list_value(&course_id).await },
            )
            .await?;
            let list: CoursewareList = serde_json::from_value(list_cached.data.clone())
                .context("parse cached courseware list")?;
            let file = list
                .files
                .iter()
                .find(|file| file.id == id)
                .cloned()
                .ok_or_else(|| anyhow::anyhow!("courseware file with id {id} not found"))?;
            let artifact_key = format!("courseware:{}", file.id);
            let url = file.url.clone();
            let download_course_id = file.course_id.clone();
            let artifact = cache::materialize_artifact(
                &artifact_key,
                &file.name,
                &out_dir,
                refresh,
                move || async move {
                    let course = load_course_by_id(&download_course_id).await?;
                    course.client().bb_bytes_by_uri_follow_redirects(&url).await
                },
            )
            .await?;
            let warnings = list_cached
                .warnings
                .into_iter()
                .chain(artifact.warnings.into_iter())
                .collect::<Vec<_>>();
            let meta = mixed_cache_meta(
                cache::CacheKind::Mixed,
                &[list_cached.meta.clone(), artifact.meta.clone()],
            );
            Ok(CommandOutcome::with_cache(
                json!({
                    "id": id,
                    "course": list.course,
                    "file": artifact.file,
                }),
                meta,
                warnings,
            ))
        }
    }
}

async fn run_explore(cmd: ExploreCommand, refresh: bool) -> anyhow::Result<CommandOutcome> {
    match cmd.command {
        ExploreCommands::Visit {
            url,
            max_chars,
            max_links,
            max_table_rows,
        } => {
            let normalized_url = api::explore::normalize_visit_url(&url)?;
            let cache_key = format!(
                "explore:visit:v1:{}:chars={}:links={}:rows={}",
                id::fnv1a64_hex(&normalized_url),
                max_chars,
                max_links,
                max_table_rows
            );
            cached_value(cache_key, metadata_ttl_explore(), refresh, || async move {
                explore_visit_value(&url, max_chars, max_links, max_table_rows).await
            })
            .await
        }
    }
}

async fn run_assignments(cmd: AssignmentsCommand, refresh: bool) -> anyhow::Result<CommandOutcome> {
    match cmd.command {
        AssignmentsCommands::List { term } => {
            cached_value(
                format!("assignments:list:{}", term.as_str()),
                metadata_ttl_short(),
                refresh,
                || async move {
                    let items = fetch_assignments(true, true, term.only_current()).await?;
                    let assignments = items
                        .iter()
                        .map(|(course, id, assignment)| assignment_json(course, id, assignment))
                        .collect::<Vec<_>>();
                    Ok(json!({"term": term, "assignments": assignments}))
                },
            )
            .await
        }
        AssignmentsCommands::Get { id, term } => {
            cached_value(
                format!("assignments:get:{}:{id}", term.as_str()),
                metadata_ttl_short(),
                refresh,
                || async move { assignment_detail_value(&id, term).await },
            )
            .await
        }
        AssignmentsCommands::Download { id, out_dir, term } => {
            let items = fetch_assignments(true, true, term.only_current()).await?;
            let Some((course, _, assignment)) =
                items.into_iter().find(|(_, item_id, _)| item_id == &id)
            else {
                bail!("assignment with id {id} not found");
            };
            let mut files = Vec::new();
            let mut metas = Vec::new();
            let mut warnings = Vec::new();
            for (name, uri) in assignment.attachments() {
                let artifact_key = format!("assignment:{id}:{uri}");
                let uri = uri.clone();
                let artifact =
                    cache::materialize_artifact(&artifact_key, name, &out_dir, refresh, || async {
                        course.client().bb_bytes_by_uri_follow_redirects(&uri).await
                    })
                    .await
                    .with_context(|| format!("download attachment {name}"))?;
                metas.push(artifact.meta);
                warnings.extend(artifact.warnings);
                files.push(serde_json::to_value(artifact.file)?);
            }
            let meta = if metas.is_empty() {
                cache::CacheMeta::disabled()
            } else if metas.len() == 1 {
                metas.remove(0)
            } else {
                mixed_cache_meta(cache::CacheKind::Artifact, &metas)
            };
            Ok(CommandOutcome::with_cache(
                json!({
                    "id": id,
                    "course": CourseJson::from(course.meta()),
                    "title": assignment.title(),
                    "out_dir": out_dir,
                    "files": files,
                }),
                meta,
                warnings,
            ))
        }
        AssignmentsCommands::DownloadSubmission { id, out_dir, term } => {
            let parts = parse_submitted_file_id(&id)?;
            let detail_cached = cache::metadata_json(
                format!("assignments:get:{}:{}", term.as_str(), parts.assignment_id),
                metadata_ttl_short(),
                refresh,
                || async { assignment_detail_value(&parts.assignment_id, term).await },
            )
            .await?;
            let submission: CourseAssignmentSubmission = serde_json::from_value(
                detail_cached
                    .data
                    .get("submission")
                    .cloned()
                    .context("submission missing from assignment detail")?,
            )
            .context("parse assignment submission detail")?;
            let mut selected_attempt = None;
            let mut selected_file = None;
            for attempt in &submission.attempts {
                if attempt.attempt_id != parts.attempt_id {
                    continue;
                }
                for file in &attempt.files {
                    if file.id == id || file.file_id == parts.file_id {
                        selected_attempt = Some(attempt.clone());
                        selected_file = Some(file.clone());
                        break;
                    }
                }
            }
            let attempt = selected_attempt.ok_or_else(|| {
                anyhow::anyhow!(
                    "attempt {} not found for submitted file {id}",
                    parts.attempt_id
                )
            })?;
            let file =
                selected_file.ok_or_else(|| anyhow::anyhow!("submitted file {id} not found"))?;
            let artifact_key = format!("assignment-submission:{}", file.id);
            let url = file.url.clone();
            let course_id = parts.course_id.clone();
            let artifact = cache::materialize_artifact(
                &artifact_key,
                &file.name,
                &out_dir,
                refresh,
                move || async move {
                    let course = load_course_by_id(&course_id).await?;
                    course.client().bb_bytes_by_uri_follow_redirects(&url).await
                },
            )
            .await?;
            let warnings = detail_cached
                .warnings
                .into_iter()
                .chain(artifact.warnings.into_iter())
                .collect::<Vec<_>>();
            let meta = mixed_cache_meta(
                cache::CacheKind::Mixed,
                &[detail_cached.meta.clone(), artifact.meta.clone()],
            );
            Ok(CommandOutcome::with_cache(
                json!({
                    "id": id,
                    "assignment": detail_cached.data.get("assignment").cloned().unwrap_or(serde_json::Value::Null),
                    "content_id": parts.content_id,
                    "attempt": attempt,
                    "file": artifact.file,
                }),
                meta,
                warnings,
            ))
        }
        AssignmentsCommands::Submit { id, file } => {
            if !file.exists() {
                bail!("file not found: {}", file.display());
            }
            let items = fetch_assignments(true, true, true).await?;
            let Some((course, _, assignment)) =
                items.into_iter().find(|(_, item_id, _)| item_id == &id)
            else {
                bail!("assignment with id {id} not found");
            };
            assignment
                .submit_file(&file)
                .await
                .with_context(|| format!("submit {} to {}", file.display(), assignment.title()))?;
            Ok(CommandOutcome::new(json!({
                "id": id,
                "course": CourseJson::from(course.meta()),
                "title": assignment.title(),
                "file": file,
                "submitted": true,
            })))
        }
    }
}

async fn run_announcements(
    cmd: AnnouncementsCommand,
    refresh: bool,
) -> anyhow::Result<CommandOutcome> {
    match cmd.command {
        AnnouncementsCommands::List { term } => {
            cached_value(
                format!("announcements:list:{}", term.as_str()),
                metadata_ttl_short(),
                refresh,
                || async move {
                    let items = fetch_announcements(true, term.only_current()).await?;
                    let announcements = items
                        .iter()
                        .map(|(course, id, announcement)| {
                            announcement_json(course, id, announcement)
                        })
                        .collect::<Vec<_>>();
                    Ok(json!({"term": term, "announcements": announcements}))
                },
            )
            .await
        }
        AnnouncementsCommands::Get { id, term } => {
            cached_value(
                format!("announcements:get:{}:{id}", term.as_str()),
                metadata_ttl_short(),
                refresh,
                || async move {
                    let items = fetch_announcements(true, term.only_current()).await?;
                    let Some((course, _, announcement)) =
                        items.into_iter().find(|(_, item_id, _)| item_id == &id)
                    else {
                        bail!("announcement with id {id} not found");
                    };
                    Ok(json!({
                        "announcement": announcement_json(&course, &id, &announcement),
                    }))
                },
            )
            .await
        }
    }
}

async fn run_timetable(cmd: TimetableCommand, refresh: bool) -> anyhow::Result<CommandOutcome> {
    match cmd.command {
        TimetableCommands::Get => {
            cached_value(
                "timetable:get",
                metadata_ttl_timetable(),
                refresh,
                || async {
                    let cfg = read_config().await?;
                    let client = build_client(false).await?;
                    let portal = client
                        .portal(&cfg.username, &cfg.password, "")
                        .await
                        .context("login to portal")?;
                    client.save_cookies().await?;
                    let raw = portal.get_my_course_table().await?;
                    let value: serde_json::Value = serde_json::from_str(&raw)?;
                    Ok(json!({"timetable": value}))
                },
            )
            .await
        }
    }
}

async fn run_videos(cmd: VideosCommand, refresh: bool) -> anyhow::Result<CommandOutcome> {
    match cmd.command {
        VideosCommands::List { term } => {
            cached_value(
                format!("videos:list:{}", term.as_str()),
                metadata_ttl_videos(),
                refresh,
                || async move {
                    let items = fetch_videos(true, term.only_current()).await?;
                    let videos = items
                        .iter()
                        .map(|(course, video)| video_json(course, video))
                        .collect::<Vec<_>>();
                    Ok(json!({"term": term, "videos": videos}))
                },
            )
            .await
        }
        VideosCommands::Download { id, out_dir, term } => {
            if !out_dir.exists() {
                fs::create_dir_all(&out_dir).await?;
            }
            let items = fetch_videos(true, term.only_current()).await?;
            let Some((course, video)) = items.into_iter().find(|(_, video)| video.id() == id)
            else {
                bail!("video with id {id} not found");
            };
            let filename = format!(
                "{}_{}.mp4",
                sanitize_filename(course.meta().name()),
                sanitize_filename(video.meta().title())
            );
            let dest = out_dir.join(&filename);
            let artifact_key = format!("video:{id}");
            let artifact_path = cache::artifact_path(&artifact_key, &filename);
            if !refresh && dest.exists() && std::fs::metadata(&dest)?.len() > 0 {
                let bytes = std::fs::metadata(&dest)?.len();
                return Ok(CommandOutcome::with_cache(
                    json!({
                        "id": id,
                        "course_name": course.meta().name(),
                        "title": video.meta().title(),
                        "file": {
                            "name": filename,
                            "path": dest,
                            "cache_hit": true,
                            "downloaded": false,
                            "bytes": bytes,
                        },
                        "segment_count": 0,
                    }),
                    cache::CacheMeta::artifact(cache::CacheMode::Hit, artifact_key),
                    Vec::new(),
                ));
            }
            if !refresh && artifact_path.exists() && std::fs::metadata(&artifact_path)?.len() > 0 {
                if let Some(parent) = dest.parent() {
                    fs::create_dir_all(parent).await?;
                }
                if dest.exists() {
                    std::fs::remove_file(&dest)?;
                }
                std::fs::hard_link(&artifact_path, &dest)
                    .or_else(|_| std::fs::copy(&artifact_path, &dest).map(|_| ()))?;
                let bytes = std::fs::metadata(&dest)?.len();
                return Ok(CommandOutcome::with_cache(
                    json!({
                        "id": id,
                        "course_name": course.meta().name(),
                        "title": video.meta().title(),
                        "file": {
                            "name": filename,
                            "path": dest,
                            "cache_hit": true,
                            "downloaded": false,
                            "bytes": bytes,
                        },
                        "segment_count": 0,
                    }),
                    cache::CacheMeta::artifact(cache::CacheMode::Hit, artifact_key),
                    Vec::new(),
                ));
            }

            let video_data = video.get().await?;
            let cache_dir = utils::projectdir()
                .cache_dir()
                .join("artifact")
                .join("video_download")
                .join(cache::safe_component(&id));
            fs::create_dir_all(&cache_dir).await?;
            let segment_paths = download_segments(&video_data, &cache_dir).await?;
            let m3u8 = cache_dir.join("playlist").with_extension("m3u8");
            buf_try!(@try fs::write(&m3u8, video_data.m3u8_raw()).await);
            let merged = cache_dir.join("merged").with_extension("ts");
            merge_segments(&merged, &segment_paths).await?;
            let output = compio::process::Command::new("ffmpeg")
                .args(["-y", "-hide_banner", "-loglevel", "quiet"])
                .args(["-i", merged.to_string_lossy().as_ref()])
                .args(["-c", "copy"])
                .arg(&dest)
                .output()
                .await
                .context("execute ffmpeg")?;
            if !output.status.success() {
                bail!("ffmpeg failed with exit code {:?}", output.status.code());
            }
            if let Some(parent) = artifact_path.parent() {
                fs::create_dir_all(parent).await?;
            }
            std::fs::copy(&dest, &artifact_path)?;
            let bytes = std::fs::metadata(&dest).map(|m| m.len()).unwrap_or(0);
            Ok(CommandOutcome::with_cache(
                json!({
                    "id": id,
                    "course_name": video_data.course_name(),
                    "title": video_data.meta().title(),
                    "file": {
                        "name": filename,
                        "path": dest,
                        "cache_hit": false,
                        "downloaded": true,
                        "bytes": bytes,
                    },
                    "segment_count": segment_paths.len(),
                }),
                cache::CacheMeta::artifact(
                    if refresh {
                        cache::CacheMode::Refresh
                    } else {
                        cache::CacheMode::Miss
                    },
                    artifact_key,
                ),
                Vec::new(),
            ))
        }
    }
}

async fn read_config() -> anyhow::Result<config::Config> {
    let cfg_path = utils::default_config_path();
    config::read_cfg(cfg_path).await.context(
        "read config file; run `pku3b auth login --username <id> --password <password>` first",
    )
}

async fn build_client(enable_cache: bool) -> anyhow::Result<api::Client> {
    let mut builder =
        api::Client::builder().cookie_restore_path(Some(utils::default_user_agent_data_path()));
    if enable_cache {
        builder = builder
            .cache_ttl(Some(std::time::Duration::from_hours(1)))
            .download_artifact_ttl(Some(std::time::Duration::from_hours(24)))
    }
    builder.build().await
}

async fn load_courses(refresh: bool, only_current: bool) -> anyhow::Result<Vec<CourseHandle>> {
    let cfg = read_config().await?;
    let client = build_client(!refresh).await?;
    let blackboard = client
        .blackboard(&cfg.username, &cfg.password, "")
        .await
        .context("login to blackboard")?;
    client.save_cookies().await?;
    blackboard
        .get_courses(only_current)
        .await
        .context("fetch courses")
}

async fn get_contents(course: &Course) -> anyhow::Result<Vec<CourseContent>> {
    let data = utils::with_cache(
        &format!("get_course_contents_{}", course.meta().id()),
        course.client().cache_ttl(),
        async {
            let mut stream = course.content_stream();
            let mut contents = Vec::new();
            while let Some(batch) = stream.next_batch().await {
                contents.extend(batch);
            }
            Ok(contents)
        },
    )
    .await?;
    Ok(data
        .into_iter()
        .map(|data| course.build_content(data))
        .collect())
}

async fn get_assignments(course: &Course) -> anyhow::Result<Vec<CourseAssignmentHandle>> {
    Ok(get_contents(course)
        .await?
        .into_iter()
        .filter_map(|content| content.into_assignment_opt())
        .collect())
}

type AssignmentItem = (Arc<Course>, String, CourseAssignment);

async fn fetch_assignments(
    refresh: bool,
    include_completed: bool,
    only_current: bool,
) -> anyhow::Result<Vec<AssignmentItem>> {
    let courses = load_courses(refresh, only_current).await?;
    let futs = courses
        .into_iter()
        .map(async move |handle| -> anyhow::Result<_> {
            let course = handle.get().await.context("fetch course")?;
            let assignments = get_assignments(&course)
                .await
                .with_context(|| format!("fetch assignments for {}", course.meta().title()))?;
            let futs = assignments
                .into_iter()
                .map(async |assignment| -> anyhow::Result<_> {
                    let id = assignment.id();
                    let data = assignment.get().await.context("fetch assignment")?;
                    Ok((id, data))
                });
            let assignments = try_join_all(futs).await?;
            Ok((course, assignments))
        });
    let courses = try_join_all(futs).await?;
    let mut items = courses
        .into_iter()
        .flat_map(|(course, assignments)| {
            let course = Arc::new(course);
            assignments
                .into_iter()
                .map(move |(id, assignment)| (course.clone(), id, assignment))
        })
        .filter(|(_, _, assignment)| include_completed || assignment.last_attempt().is_none())
        .collect::<Vec<_>>();
    items.sort_by_cached_key(|(_, _, assignment)| assignment.deadline());
    Ok(items)
}

type AnnouncementItem = (Arc<Course>, String, CourseAnnouncementHandle);

async fn fetch_announcements(
    refresh: bool,
    only_current: bool,
) -> anyhow::Result<Vec<AnnouncementItem>> {
    let courses = load_courses(refresh, only_current).await?;
    let futs = courses
        .into_iter()
        .map(async move |handle| -> anyhow::Result<_> {
            let course = handle.get().await.context("fetch course")?;
            let announcements = course
                .list_announcements_from_coursepage()
                .await
                .with_context(|| format!("fetch announcements for {}", course.meta().title()))?;
            Ok((course, announcements))
        });
    let courses = try_join_all(futs).await?;
    let mut items = courses
        .into_iter()
        .flat_map(|(course, announcements)| {
            let course = Arc::new(course);
            announcements
                .into_iter()
                .map(move |announcement| (course.clone(), announcement.id(), announcement))
        })
        .collect::<Vec<_>>();
    items.sort_by(|a, b| match (b.2.time(), a.2.time()) {
        (Some(time_b), Some(time_a)) => time_b.cmp(time_a),
        (Some(_), None) => std::cmp::Ordering::Less,
        (None, Some(_)) => std::cmp::Ordering::Greater,
        (None, None) => std::cmp::Ordering::Equal,
    });
    Ok(items)
}

type VideoItem = (Arc<Course>, CourseVideoHandle);

async fn fetch_videos(refresh: bool, only_current: bool) -> anyhow::Result<Vec<VideoItem>> {
    let courses = load_courses(refresh, only_current).await?;
    let futs = courses
        .into_iter()
        .map(async move |handle| -> anyhow::Result<_> {
            let course = handle.get().await.context("fetch course")?;
            let videos = course
                .get_video_list()
                .await
                .with_context(|| format!("fetch videos for {}", course.meta().title()))?;
            Ok((course, videos))
        });
    let courses = try_join_all(futs).await?;
    Ok(courses
        .into_iter()
        .flat_map(|(course, videos)| {
            let course = Arc::new(course);
            videos.into_iter().map(move |video| (course.clone(), video))
        })
        .collect())
}

fn attachment_json((name, url): &(String, String)) -> AttachmentJson {
    AttachmentJson {
        name: name.clone(),
        url: url.clone(),
    }
}

fn assignment_json(course: &Course, id: &str, assignment: &CourseAssignment) -> AssignmentJson {
    AssignmentJson {
        id: id.to_owned(),
        course: CourseJson::from(course.meta()),
        title: assignment.title().to_owned(),
        descriptions: assignment.descriptions().to_vec(),
        attachments: assignment
            .attachments()
            .iter()
            .map(attachment_json)
            .collect(),
        deadline_raw: assignment.deadline_raw().map(ToOwned::to_owned),
        deadline: assignment.deadline().map(|deadline| deadline.to_rfc3339()),
        last_attempt: assignment.last_attempt().map(ToOwned::to_owned),
        submitted: assignment.submission_summary().submitted,
        submission_summary: assignment.submission_summary().clone(),
    }
}

fn announcement_json(
    course: &Course,
    id: &str,
    announcement: &CourseAnnouncementHandle,
) -> AnnouncementJson {
    AnnouncementJson {
        id: id.to_owned(),
        course: CourseJson::from(course.meta()),
        title: announcement.title().to_owned(),
        time_raw: announcement.time().map(ToOwned::to_owned),
        descriptions: announcement.descriptions().to_vec(),
        attachments: announcement
            .attachments()
            .iter()
            .map(attachment_json)
            .collect(),
    }
}

fn video_json(course: &Course, video: &CourseVideoHandle) -> VideoJson {
    VideoJson {
        id: video.id(),
        course: CourseJson::from(course.meta()),
        title: video.meta().title().to_owned(),
        time_raw: video.meta().time().to_owned(),
    }
}

async fn download_segments(
    video: &CourseVideo,
    dir: impl AsRef<std::path::Path>,
) -> anyhow::Result<Vec<std::path::PathBuf>> {
    let dir = dir.as_ref();
    if !dir.exists() {
        bail!("dir {} not exists", dir.display());
    }
    let mut key = None;
    let mut paths = Vec::new();
    for index in 0..video.len_segments() {
        key = video.refresh_key(index, key);
        let path = dir.join(&video.segment(index).uri).with_extension("ts");
        if !path.exists() {
            let segment = video
                .get_segment_data(index, key)
                .await
                .with_context(|| format!("get segment #{index}"))?;
            let tmp = path.with_extension("tmp");
            buf_try!(@try fs::write(&tmp, segment).await);
            fs::rename(tmp, &path).await?;
        }
        paths.push(path);
    }
    Ok(paths)
}

async fn merge_segments(
    dest: impl AsRef<std::path::Path>,
    paths: &[std::path::PathBuf],
) -> anyhow::Result<()> {
    let file = fs::File::create(&dest).await?;
    let mut file = std::io::Cursor::new(file);
    for path in paths {
        let data = fs::read(path).await?;
        buf_try!(@try file.write(data).await);
    }
    Ok(())
}

fn sanitize_filename(value: &str) -> String {
    value
        .chars()
        .map(|ch| match ch {
            '/' | '\\' | ':' | '*' | '?' | '"' | '<' | '>' | '|' => '_',
            _ => ch,
        })
        .collect()
}
