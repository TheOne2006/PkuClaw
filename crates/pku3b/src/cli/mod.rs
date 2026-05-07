mod output;

use crate::api::blackboard::*;
use crate::{api, build, config, utils};
use anyhow::{Context as _, bail};
use clap::{Parser, Subcommand, ValueEnum};
use compio::{buf::buf_try, fs, io::AsyncWrite};
use futures_util::future::try_join_all;
use serde::Serialize;
use serde_json::json;
use std::{path::PathBuf, sync::Arc};

pub use output::{anyhow_to_error, clap_error_to_error, exit_code, print_error};

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
    Clean,
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
    Download {
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
}

#[derive(Debug, Serialize)]
struct CourseJson {
    id: String,
    title: String,
    name: String,
    is_current: bool,
}

impl From<&CourseMeta> for CourseJson {
    fn from(meta: &CourseMeta) -> Self {
        Self {
            id: meta.id().to_owned(),
            title: meta.title().to_owned(),
            name: meta.name().to_owned(),
            is_current: meta.is_current(),
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
    let data = match cli.command {
        Commands::Auth(cmd) => run_auth(cmd).await?,
        Commands::Config(cmd) => run_config(cmd).await?,
        Commands::Cache(cmd) => run_cache(cmd).await?,
        Commands::Assignments(cmd) => run_assignments(cmd, refresh).await?,
        Commands::Announcements(cmd) => run_announcements(cmd, refresh).await?,
        Commands::Timetable(cmd) => run_timetable(cmd, refresh).await?,
        Commands::Videos(cmd) => run_videos(cmd, refresh).await?,
    };
    output::print_ok(data, pretty)
}

async fn run_auth(cmd: AuthCommand) -> anyhow::Result<serde_json::Value> {
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

            Ok(json!({
                "config_path": cfg_path,
                "cookie_path": utils::default_user_agent_data_path(),
                "username": cfg.username,
                "blackboard_authenticated": true,
                "portal_authenticated": portal_login.is_ok(),
            }))
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
            Ok(json!({
                "config_present": config_present,
                "cookie_present": cookie_present,
                "username": username,
                "blackboard_authenticated": blackboard_authenticated,
                "config_path": cfg_path,
                "cookie_path": cookie_path,
            }))
        }
        AuthCommands::Logout => {
            let cookie_path = utils::default_user_agent_data_path();
            let removed = if cookie_path.exists() {
                fs::remove_file(&cookie_path).await?;
                true
            } else {
                false
            };
            Ok(json!({
                "cookie_path": cookie_path,
                "removed": removed,
            }))
        }
    }
}

async fn run_config(cmd: ConfigCommand) -> anyhow::Result<serde_json::Value> {
    let cfg_path = utils::default_config_path();
    match cmd.command {
        ConfigCommands::Get { key } => {
            let cfg = config::read_cfg(&cfg_path).await.context("read config")?;
            let data = match key {
                Some(ConfigKey::Username) => json!({"username": cfg.username}),
                Some(ConfigKey::Password) => json!({"password": cfg.password}),
                None => serde_json::to_value(&cfg)?,
            };
            Ok(json!({"config_path": cfg_path, "config": data}))
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
            Ok(json!({"config_path": cfg_path, "updated": true}))
        }
    }
}

async fn run_cache(cmd: CacheCommand) -> anyhow::Result<serde_json::Value> {
    match cmd.command {
        CacheCommands::Status => {
            let dir = utils::projectdir().cache_dir().to_path_buf();
            let (files, bytes) = cache_stats(&dir)?;
            Ok(json!({"cache_dir": dir, "files": files, "bytes": bytes}))
        }
        CacheCommands::Clean => {
            let dir = utils::projectdir().cache_dir().to_path_buf();
            let (files, bytes) = cache_stats(&dir)?;
            if dir.exists() {
                std::fs::remove_dir_all(&dir)?;
            }
            Ok(json!({
                "cache_dir": dir,
                "removed_files": files,
                "removed_bytes": bytes,
            }))
        }
    }
}

fn cache_stats(dir: &std::path::Path) -> anyhow::Result<(u64, u64)> {
    fn walk(path: &std::path::Path, files: &mut u64, bytes: &mut u64) -> anyhow::Result<()> {
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

async fn run_assignments(
    cmd: AssignmentsCommand,
    refresh: bool,
) -> anyhow::Result<serde_json::Value> {
    match cmd.command {
        AssignmentsCommands::List { term } => {
            let items = fetch_assignments(refresh, true, term.only_current()).await?;
            let assignments = items
                .iter()
                .map(|(course, id, assignment)| assignment_json(course, id, assignment))
                .collect::<Vec<_>>();
            Ok(json!({"term": term, "assignments": assignments}))
        }
        AssignmentsCommands::Download { id, out_dir, term } => {
            let items = fetch_assignments(refresh, true, term.only_current()).await?;
            let Some((course, _, assignment)) =
                items.into_iter().find(|(_, item_id, _)| item_id == &id)
            else {
                bail!("assignment with id {id} not found");
            };
            if !out_dir.exists() {
                fs::create_dir_all(&out_dir).await?;
            }
            let mut files = Vec::new();
            for (name, uri) in assignment.attachments() {
                let dest = out_dir.join(name);
                assignment
                    .download_attachment(uri, &dest)
                    .await
                    .with_context(|| format!("download attachment {name}"))?;
                files.push(json!({"name": name, "path": dest}));
            }
            Ok(json!({
                "id": id,
                "course": CourseJson::from(course.meta()),
                "title": assignment.title(),
                "out_dir": out_dir,
                "files": files,
            }))
        }
        AssignmentsCommands::Submit { id, file } => {
            if !file.exists() {
                bail!("file not found: {}", file.display());
            }
            let items = fetch_assignments(false, true, true).await?;
            let Some((course, _, assignment)) =
                items.into_iter().find(|(_, item_id, _)| item_id == &id)
            else {
                bail!("assignment with id {id} not found");
            };
            assignment
                .submit_file(&file)
                .await
                .with_context(|| format!("submit {} to {}", file.display(), assignment.title()))?;
            Ok(json!({
                "id": id,
                "course": CourseJson::from(course.meta()),
                "title": assignment.title(),
                "file": file,
                "submitted": true,
            }))
        }
    }
}

async fn run_announcements(
    cmd: AnnouncementsCommand,
    refresh: bool,
) -> anyhow::Result<serde_json::Value> {
    match cmd.command {
        AnnouncementsCommands::List { term } => {
            let items = fetch_announcements(refresh, term.only_current()).await?;
            let announcements = items
                .iter()
                .map(|(course, id, announcement)| announcement_json(course, id, announcement))
                .collect::<Vec<_>>();
            Ok(json!({"term": term, "announcements": announcements}))
        }
        AnnouncementsCommands::Get { id, term } => {
            let items = fetch_announcements(refresh, term.only_current()).await?;
            let Some((course, _, announcement)) =
                items.into_iter().find(|(_, item_id, _)| item_id == &id)
            else {
                bail!("announcement with id {id} not found");
            };
            Ok(json!({
                "announcement": announcement_json(&course, &id, &announcement),
            }))
        }
    }
}

async fn run_timetable(cmd: TimetableCommand, refresh: bool) -> anyhow::Result<serde_json::Value> {
    match cmd.command {
        TimetableCommands::Get => {
            let cfg = read_config().await?;
            let client = build_client(!refresh).await?;
            let portal = client
                .portal(&cfg.username, &cfg.password, "")
                .await
                .context("login to portal")?;
            client.save_cookies().await?;
            let raw = portal.get_my_course_table().await?;
            let value: serde_json::Value = serde_json::from_str(&raw)?;
            Ok(json!({"timetable": value}))
        }
    }
}

async fn run_videos(cmd: VideosCommand, refresh: bool) -> anyhow::Result<serde_json::Value> {
    match cmd.command {
        VideosCommands::List { term } => {
            let items = fetch_videos(refresh, term.only_current()).await?;
            let videos = items
                .iter()
                .map(|(course, video)| video_json(course, video))
                .collect::<Vec<_>>();
            Ok(json!({"term": term, "videos": videos}))
        }
        VideosCommands::Download { id, out_dir, term } => {
            if !out_dir.exists() {
                fs::create_dir_all(&out_dir).await?;
            }
            let items = fetch_videos(refresh, term.only_current()).await?;
            let Some((_, video)) = items.into_iter().find(|(_, video)| video.id() == id) else {
                bail!("video with id {id} not found");
            };
            let video_data = video.get().await?;
            let cache_dir = utils::projectdir()
                .cache_dir()
                .join("video_download")
                .join(&id);
            fs::create_dir_all(&cache_dir).await?;
            let segment_paths = download_segments(&video_data, &cache_dir).await?;
            let m3u8 = cache_dir.join("playlist").with_extension("m3u8");
            buf_try!(@try fs::write(&m3u8, video_data.m3u8_raw()).await);
            let merged = cache_dir.join("merged").with_extension("ts");
            merge_segments(&merged, &segment_paths).await?;
            let dest = out_dir.join(format!(
                "{}_{}.mp4",
                sanitize_filename(video_data.course_name()),
                sanitize_filename(video_data.meta().title())
            ));
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
            Ok(json!({
                "id": id,
                "course_name": video_data.course_name(),
                "title": video_data.meta().title(),
                "path": dest,
                "segment_count": segment_paths.len(),
            }))
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
        submitted: assignment.last_attempt().is_some(),
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
