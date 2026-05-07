use serde::Serialize;
use serde_json::json;

use crate::cache::CacheMeta;

pub const SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Clone, Serialize)]
pub struct ErrorItem {
    pub code: String,
    pub message: String,
    pub recoverable: bool,
}

#[derive(Debug, Serialize)]
struct Envelope<T: Serialize> {
    ok: bool,
    data: Option<T>,
    warnings: Vec<String>,
    errors: Vec<ErrorItem>,
    meta: serde_json::Value,
}

#[derive(Debug, Clone, Serialize)]
pub struct CommandOutcome {
    pub data: serde_json::Value,
    pub warnings: Vec<String>,
    pub cache: CacheMeta,
}

impl CommandOutcome {
    pub fn new(data: serde_json::Value) -> Self {
        Self {
            data,
            warnings: Vec::new(),
            cache: CacheMeta::disabled(),
        }
    }

    pub fn with_cache(data: serde_json::Value, cache: CacheMeta, warnings: Vec<String>) -> Self {
        Self {
            data,
            warnings,
            cache,
        }
    }
}

pub fn print_ok(outcome: CommandOutcome, pretty: bool) -> anyhow::Result<()> {
    let envelope = Envelope {
        ok: true,
        data: Some(outcome.data),
        warnings: outcome.warnings,
        errors: Vec::new(),
        meta: json!({
            "schema_version": SCHEMA_VERSION,
            "generated_at": chrono::Local::now().to_rfc3339(),
            "cache": outcome.cache,
        }),
    };
    print_json(&envelope, pretty)
}

pub fn print_error(error: ErrorItem, pretty: bool) {
    let envelope = Envelope::<serde_json::Value> {
        ok: false,
        data: None,
        warnings: Vec::new(),
        errors: vec![error],
        meta: json!({
            "schema_version": SCHEMA_VERSION,
            "generated_at": chrono::Local::now().to_rfc3339(),
            "cache": CacheMeta::disabled(),
        }),
    };
    let _ = print_json(&envelope, pretty);
}

pub fn anyhow_to_error(err: anyhow::Error) -> ErrorItem {
    let message = format!("{err:#}");
    let lower = message.to_ascii_lowercase();
    let code = if lower.contains("invalid_url") {
        "invalid_url"
    } else if lower.contains("url_not_allowed") {
        "url_not_allowed"
    } else if lower.contains("otp") || message.contains("手机令牌") {
        "otp_required"
    } else if lower.contains("login")
        || lower.contains("auth")
        || lower.contains("unauthorized")
        || message.contains("登录")
    {
        "auth_required"
    } else if lower.contains("not found") || message.contains("不存在") {
        "not_found"
    } else if lower.contains("network")
        || lower.contains("dns")
        || lower.contains("connect")
        || lower.contains("timeout")
    {
        "network_error"
    } else if lower.contains("parse") || lower.contains("selector") {
        "parse_error"
    } else {
        "general_error"
    };
    let recoverable = matches!(
        code,
        "otp_required"
            | "auth_required"
            | "network_error"
            | "not_found"
            | "invalid_url"
            | "url_not_allowed"
    );
    ErrorItem {
        code: code.to_owned(),
        message,
        recoverable,
    }
}

pub fn clap_error_to_error(err: clap::Error) -> ErrorItem {
    ErrorItem {
        code: "invalid_args".to_owned(),
        message: err.to_string(),
        recoverable: true,
    }
}

pub fn exit_code(error: &ErrorItem) -> i32 {
    match error.code.as_str() {
        "invalid_args" => 2,
        "auth_required" | "otp_required" => 3,
        "invalid_url" | "url_not_allowed" => 2,
        "network_error" => 4,
        "parse_error" => 5,
        _ => 1,
    }
}

fn print_json<T: Serialize>(value: &T, pretty: bool) -> anyhow::Result<()> {
    if pretty {
        println!("{}", serde_json::to_string_pretty(value)?);
    } else {
        println!("{}", serde_json::to_string(value)?);
    }
    Ok(())
}
