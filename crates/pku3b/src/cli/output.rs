use serde::Serialize;
use serde_json::json;

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

pub fn print_ok<T: Serialize>(data: T, pretty: bool) -> anyhow::Result<()> {
    let envelope = Envelope {
        ok: true,
        data: Some(data),
        warnings: Vec::new(),
        errors: Vec::new(),
        meta: json!({
            "schema_version": SCHEMA_VERSION,
            "generated_at": chrono::Local::now().to_rfc3339(),
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
        }),
    };
    let _ = print_json(&envelope, pretty);
}

pub fn anyhow_to_error(err: anyhow::Error) -> ErrorItem {
    let message = format!("{err:#}");
    let lower = message.to_ascii_lowercase();
    let code = if lower.contains("otp") || message.contains("手机令牌") {
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
        "otp_required" | "auth_required" | "network_error" | "not_found"
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
