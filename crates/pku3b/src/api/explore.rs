//! Authenticated, read-only Blackboard page exploration.
//!
//! This module intentionally exposes a constrained "visit" surface for PkuClaw:
//! it performs one GET request, follows safe Blackboard redirects, and returns a
//! cleaned/structured representation of the page. It is not a browser, crawler,
//! form submitter, or arbitrary network client.

use anyhow::{Context as _, bail};
use scraper::{ElementRef, Html, Selector, node::Node};
use serde::{Deserialize, Serialize};
use url::Url;

use crate::{api::Client, id};

const DEFAULT_BASE_URL: &str = "https://course.pku.edu.cn/";
const MAX_REDIRECTS: usize = 8;
const MAX_BODY_BYTES: usize = 4 * 1024 * 1024;
const MAX_OUTPUT_CHARS_HARD: usize = 100_000;
const MAX_LINKS_HARD: usize = 1_000;
const MAX_TABLE_ROWS_HARD: usize = 1_000;
const MAX_HREF_CHARS: usize = 2_048;

const ALLOWED_VISIT_HOSTS: &[&str] = &["course.pku.edu.cn"];

#[derive(Debug, Clone, Copy)]
pub struct ExploreVisitOptions {
    pub max_chars: usize,
    pub max_links: usize,
    pub max_table_rows: usize,
}

impl Default for ExploreVisitOptions {
    fn default() -> Self {
        Self {
            max_chars: 20_000,
            max_links: 200,
            max_table_rows: 100,
        }
    }
}

impl ExploreVisitOptions {
    fn effective(self) -> Self {
        Self {
            max_chars: self.max_chars.min(MAX_OUTPUT_CHARS_HARD),
            max_links: self.max_links.min(MAX_LINKS_HARD),
            max_table_rows: self.max_table_rows.min(MAX_TABLE_ROWS_HARD),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExploreVisitResult {
    pub requested_url: String,
    pub normalized_url: String,
    pub final_url: String,
    pub status: u16,
    pub content_type: Option<String>,
    pub content_length: Option<u64>,
    pub body_bytes_read: Option<usize>,
    pub body_truncated: bool,
    pub text_truncated: bool,
    pub title: Option<String>,
    pub main_text: String,
    pub headings: Vec<ExploreHeading>,
    pub links: Vec<ExploreLink>,
    pub attachments: Vec<ExploreAttachment>,
    pub tables: Vec<ExploreTable>,
    pub forms: Vec<ExploreForm>,
    pub blackboard: ExploreBlackboardHints,
    pub redirects: Vec<ExploreRedirect>,
    pub limits: ExploreLimits,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExploreLimits {
    pub max_chars: usize,
    pub max_links: usize,
    pub max_table_rows: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExploreRedirect {
    pub status: u16,
    pub from: String,
    pub to: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExploreHeading {
    pub level: u8,
    pub text: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExploreLink {
    pub id: String,
    pub text: String,
    pub href: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub href_scheme: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub absolute_url: Option<String>,
    pub kind: String,
    pub visit_allowed: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExploreAttachment {
    pub id: String,
    pub name: String,
    pub url: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub absolute_url: Option<String>,
    pub kind: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExploreTable {
    pub id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub caption: Option<String>,
    pub rows: Vec<Vec<String>>,
    pub truncated: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExploreForm {
    pub id: String,
    pub method: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub action: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub absolute_action: Option<String>,
    pub submit_supported: bool,
    pub controls: Vec<ExploreFormControl>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExploreFormControl {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    #[serde(rename = "type")]
    pub control_type: String,
    pub value_present: bool,
    pub value_redacted: bool,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ExploreBlackboardHints {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub course_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub content_id: Option<String>,
}

impl Client {
    pub async fn explore_visit(
        &self,
        input_url: &str,
        options: ExploreVisitOptions,
    ) -> anyhow::Result<ExploreVisitResult> {
        let options = options.effective();
        let normalized_url = normalize_visit_url(input_url)?;
        let mut current_url = normalized_url.clone();
        let mut redirects = Vec::new();

        loop {
            let res = self.get_by_uri(&current_url).await?;
            let status = res.status();
            if status.is_redirection() {
                if redirects.len() >= MAX_REDIRECTS {
                    bail!("network_error: too many redirects while visiting {normalized_url}");
                }
                let location = res
                    .headers()
                    .get(http::header::LOCATION)
                    .context("network_error: redirect response missing Location header")?
                    .to_str()
                    .context("network_error: redirect Location header is not valid text")?;
                let next_url = normalize_redirect_url(&current_url, location)?;
                redirects.push(ExploreRedirect {
                    status: status.as_u16(),
                    from: current_url,
                    to: next_url.clone(),
                });
                current_url = next_url;
                continue;
            }

            let content_type = header_to_string(res.headers().get(http::header::CONTENT_TYPE));
            let content_length = header_to_string(res.headers().get(http::header::CONTENT_LENGTH))
                .and_then(|s| s.parse::<u64>().ok());

            if !is_text_like(content_type.as_deref()) {
                return Ok(ExploreVisitResult {
                    requested_url: input_url.to_owned(),
                    normalized_url,
                    final_url: current_url.clone(),
                    status: status.as_u16(),
                    content_type,
                    content_length,
                    body_bytes_read: None,
                    body_truncated: false,
                    text_truncated: false,
                    title: None,
                    main_text: String::new(),
                    headings: Vec::new(),
                    links: Vec::new(),
                    attachments: Vec::new(),
                    tables: Vec::new(),
                    forms: Vec::new(),
                    blackboard: blackboard_hints(&current_url),
                    redirects,
                    limits: ExploreLimits {
                        max_chars: options.max_chars,
                        max_links: options.max_links,
                        max_table_rows: options.max_table_rows,
                    },
                });
            }

            let bytes = res.bytes().await?;
            let body_truncated = bytes.len() > MAX_BODY_BYTES;
            let body_bytes = bytes.len().min(MAX_BODY_BYTES);
            let body = String::from_utf8_lossy(&bytes[..body_bytes]).into_owned();
            let mut result = parse_explore_html(&body, &current_url, options)?;
            result.requested_url = input_url.to_owned();
            result.normalized_url = normalized_url;
            result.final_url = current_url.clone();
            result.status = status.as_u16();
            result.content_type = content_type;
            result.content_length = content_length;
            result.body_bytes_read = Some(body_bytes);
            result.body_truncated = body_truncated;
            result.redirects = redirects;
            return Ok(result);
        }
    }
}

pub fn normalize_visit_url(input: &str) -> anyhow::Result<String> {
    let base = Url::parse(DEFAULT_BASE_URL).expect("static base URL is valid");
    let trimmed = input.trim();
    if trimmed.is_empty() {
        bail!("invalid_url: empty URL");
    }
    let url = if trimmed.starts_with("//") {
        Url::parse(&format!("https:{trimmed}"))
            .context("invalid_url: parse protocol-relative URL")?
    } else if let Ok(url) = Url::parse(trimmed) {
        url
    } else {
        base.join(trimmed)
            .with_context(|| format!("invalid_url: parse relative URL {trimmed:?}"))?
    };
    validate_visit_target(&url)?;
    Ok(url.to_string())
}

fn normalize_redirect_url(current_url: &str, location: &str) -> anyhow::Result<String> {
    let current = Url::parse(current_url).context("invalid_url: current redirect URL invalid")?;
    let next = if location.trim_start().starts_with("//") {
        Url::parse(&format!("https:{}", location.trim()))
            .context("invalid_url: parse protocol-relative redirect URL")?
    } else {
        current
            .join(location.trim())
            .with_context(|| format!("invalid_url: parse redirect URL {location:?}"))?
    };
    validate_visit_target(&next)?;
    Ok(next.to_string())
}

fn validate_visit_target(url: &Url) -> anyhow::Result<()> {
    match url.scheme() {
        "http" | "https" => {}
        scheme => bail!("invalid_url: scheme {scheme:?} cannot be used as a visit target"),
    }

    let host = url
        .host_str()
        .context("invalid_url: visit target must have a host")?;
    if !ALLOWED_VISIT_HOSTS
        .iter()
        .any(|allowed| host.eq_ignore_ascii_case(allowed))
    {
        bail!("url_not_allowed: host {host:?} is not in pku3b explore allowlist");
    }

    if let Some(port) = url.port() {
        let allowed =
            (url.scheme() == "http" && port == 80) || (url.scheme() == "https" && port == 443);
        if !allowed {
            bail!("url_not_allowed: non-default port {port} is not allowed");
        }
    }

    if let Some(reason) = unsafe_get_reason(url) {
        bail!("url_not_allowed: GET target may change remote state ({reason})");
    }

    Ok(())
}

fn unsafe_get_reason(url: &Url) -> Option<&'static str> {
    let path = url.path().to_ascii_lowercase();
    for (key, value) in url.query_pairs() {
        let key = key.to_ascii_lowercase();
        let value = value.to_ascii_lowercase();
        if key == "action"
            && matches!(
                value.as_ref(),
                "logout"
                    | "delete"
                    | "remove"
                    | "submit"
                    | "save"
                    | "upload"
                    | "newattempt"
                    | "start"
                    | "attempt"
            )
        {
            return Some("unsafe action query");
        }
        if key == "method"
            && matches!(
                value.as_ref(),
                "delete" | "remove" | "submit" | "save" | "update"
            )
        {
            return Some("unsafe method query");
        }
    }
    if path.contains("/webapps/login/") && url.query().is_some_and(|q| q.contains("logout")) {
        return Some("logout URL");
    }
    None
}

fn parse_explore_html(
    html: &str,
    final_url: &str,
    options: ExploreVisitOptions,
) -> anyhow::Result<ExploreVisitResult> {
    let dom = Html::parse_document(html);
    let title = select_first_text(&dom, "title");
    let (main_text, text_truncated) = extract_main_text(&dom, options.max_chars);
    let headings = extract_headings(&dom);
    let links = extract_links(&dom, final_url, options.max_links)?;
    let attachments = links
        .iter()
        .filter(|link| link.kind == "webdav")
        .map(|link| ExploreAttachment {
            id: link.id.clone(),
            name: if link.text.is_empty() {
                "attachment".to_owned()
            } else {
                link.text.clone()
            },
            url: link.href.clone(),
            absolute_url: link.absolute_url.clone(),
            kind: "webdav".to_owned(),
        })
        .collect();
    let tables = extract_tables(&dom, options.max_table_rows);
    let forms = extract_forms(&dom, final_url)?;

    Ok(ExploreVisitResult {
        requested_url: String::new(),
        normalized_url: String::new(),
        final_url: final_url.to_owned(),
        status: 0,
        content_type: None,
        content_length: None,
        body_bytes_read: None,
        body_truncated: false,
        text_truncated,
        title,
        main_text,
        headings,
        links,
        attachments,
        tables,
        forms,
        blackboard: blackboard_hints(final_url),
        redirects: Vec::new(),
        limits: ExploreLimits {
            max_chars: options.max_chars,
            max_links: options.max_links,
            max_table_rows: options.max_table_rows,
        },
    })
}

fn select_first_text(dom: &Html, selector: &str) -> Option<String> {
    let selector = Selector::parse(selector).ok()?;
    dom.select(&selector)
        .map(|el| normalize_text(&el.text().collect::<String>()))
        .find(|text| !text.is_empty())
}

fn extract_main_text(dom: &Html, max_chars: usize) -> (String, bool) {
    let body_selector = Selector::parse("body").unwrap();
    let root = dom
        .select(&body_selector)
        .next()
        .or_else(|| dom.root_element().child_elements().next());
    let Some(root) = root else {
        return (String::new(), false);
    };
    let mut raw = String::new();
    collect_visible_text(root, &mut raw);
    let text = normalize_text(&raw);
    truncate_chars(&text, max_chars)
}

fn collect_visible_text(element: ElementRef<'_>, out: &mut String) {
    if should_skip_text_element(element.value().name()) {
        return;
    }
    for child in element.children() {
        match child.value() {
            Node::Text(text) => {
                let text = text.trim();
                if !text.is_empty() {
                    out.push(' ');
                    out.push_str(text);
                }
            }
            Node::Element(_) => {
                if let Some(child_element) = ElementRef::wrap(child) {
                    collect_visible_text(child_element, out);
                }
            }
            _ => {}
        }
    }
}

fn should_skip_text_element(name: &str) -> bool {
    matches!(
        name,
        "script" | "style" | "noscript" | "template" | "svg" | "nav" | "footer" | "header"
    )
}

fn extract_headings(dom: &Html) -> Vec<ExploreHeading> {
    let selector = Selector::parse("h1, h2, h3, h4, h5, h6").unwrap();
    dom.select(&selector)
        .filter_map(|el| {
            let text = normalize_text(&el.text().collect::<String>());
            if text.is_empty() {
                return None;
            }
            let level = el
                .value()
                .name()
                .strip_prefix('h')
                .and_then(|s| s.parse::<u8>().ok())
                .unwrap_or(0);
            Some(ExploreHeading { level, text })
        })
        .collect()
}

fn extract_links(
    dom: &Html,
    final_url: &str,
    max_links: usize,
) -> anyhow::Result<Vec<ExploreLink>> {
    let selector = Selector::parse("a[href]").unwrap();
    let base = Url::parse(final_url).context("invalid_url: final URL cannot be used as base")?;
    let mut links = Vec::new();
    for (index, a) in dom.select(&selector).enumerate() {
        if links.len() >= max_links {
            break;
        }
        let raw_href = a.value().attr("href").unwrap_or_default().trim();
        let text = normalize_text(&a.text().collect::<String>());
        let classified = classify_href(raw_href, &base);
        let href = sanitize_href(raw_href);
        let id = format!(
            "fnv1a64:{}",
            id::fnv1a64_hex(&format!(
                "{final_url}\nlink:{index}\nhref:{raw_href}\ntext:{text}"
            ))
        );
        links.push(ExploreLink {
            id,
            text,
            href,
            href_scheme: classified.scheme,
            absolute_url: classified.absolute_url,
            kind: classified.kind,
            visit_allowed: classified.visit_allowed,
            reason: classified.reason,
        });
    }
    Ok(links)
}

struct ClassifiedHref {
    scheme: Option<String>,
    absolute_url: Option<String>,
    kind: String,
    visit_allowed: bool,
    reason: Option<String>,
}

fn classify_href(raw_href: &str, base: &Url) -> ClassifiedHref {
    let href = raw_href.trim();
    if href.is_empty() {
        return ClassifiedHref {
            scheme: None,
            absolute_url: None,
            kind: "unknown".to_owned(),
            visit_allowed: false,
            reason: Some("empty_href".to_owned()),
        };
    }

    if href.starts_with('#') {
        return ClassifiedHref {
            scheme: Some("fragment".to_owned()),
            absolute_url: None,
            kind: "anchor".to_owned(),
            visit_allowed: false,
            reason: Some("fragment_only".to_owned()),
        };
    }

    let maybe_url = if href.starts_with("//") {
        Url::parse(&format!("https:{href}"))
    } else if let Ok(url) = Url::parse(href) {
        Ok(url)
    } else {
        base.join(href)
    };

    let Ok(url) = maybe_url else {
        return ClassifiedHref {
            scheme: None,
            absolute_url: None,
            kind: "unknown".to_owned(),
            visit_allowed: false,
            reason: Some("parse_failed".to_owned()),
        };
    };

    let scheme = url.scheme().to_owned();
    if scheme != "http" && scheme != "https" {
        return ClassifiedHref {
            scheme: Some(scheme),
            absolute_url: None,
            kind: "unsafe".to_owned(),
            visit_allowed: false,
            reason: Some("non_http_scheme".to_owned()),
        };
    }

    let absolute_url = url.to_string();
    let host_allowed = url.host_str().is_some_and(|host| {
        ALLOWED_VISIT_HOSTS
            .iter()
            .any(|allowed| host.eq_ignore_ascii_case(allowed))
    });
    let disallow_reason = match validate_visit_target(&url) {
        Ok(()) => None,
        Err(err) => {
            let message = err.to_string();
            if message.contains("GET target may change remote state") {
                Some("unsafe_get_action")
            } else {
                Some("host_not_allowed")
            }
        }
    };
    let visit_allowed = disallow_reason.is_none();
    let kind = if !host_allowed {
        "external"
    } else if url.path().contains("/bbcswebdav/") {
        "webdav"
    } else if url.path().contains("/webapps/") {
        "blackboard"
    } else {
        "internal"
    }
    .to_owned();
    ClassifiedHref {
        scheme: Some(scheme),
        absolute_url: Some(absolute_url),
        kind,
        visit_allowed,
        reason: disallow_reason.map(ToOwned::to_owned),
    }
}

fn extract_tables(dom: &Html, max_table_rows: usize) -> Vec<ExploreTable> {
    let table_selector = Selector::parse("table").unwrap();
    let caption_selector = Selector::parse("caption").unwrap();
    let row_selector = Selector::parse("tr").unwrap();
    let cell_selector = Selector::parse("th, td").unwrap();

    dom.select(&table_selector)
        .enumerate()
        .map(|(index, table)| {
            let caption = table
                .select(&caption_selector)
                .next()
                .map(|el| normalize_text(&el.text().collect::<String>()))
                .filter(|s| !s.is_empty());
            let mut rows = Vec::new();
            let mut truncated = false;
            for row in table.select(&row_selector) {
                if rows.len() >= max_table_rows {
                    truncated = true;
                    break;
                }
                let cells = row
                    .select(&cell_selector)
                    .map(|cell| normalize_text(&cell.text().collect::<String>()))
                    .collect::<Vec<_>>();
                if !cells.is_empty() {
                    rows.push(cells);
                }
            }
            ExploreTable {
                id: format!("fnv1a64:{}", id::fnv1a64_hex(&format!("table:{index}"))),
                caption,
                rows,
                truncated,
            }
        })
        .collect()
}

fn extract_forms(dom: &Html, final_url: &str) -> anyhow::Result<Vec<ExploreForm>> {
    let form_selector = Selector::parse("form").unwrap();
    let control_selector = Selector::parse("input, select, textarea, button").unwrap();
    let base = Url::parse(final_url).context("invalid_url: final URL cannot be used as base")?;

    dom.select(&form_selector)
        .enumerate()
        .map(|(index, form)| {
            let method = form
                .value()
                .attr("method")
                .unwrap_or("GET")
                .trim()
                .to_ascii_uppercase();
            let action = form.value().attr("action").map(|s| s.trim().to_owned());
            let absolute_action = action.as_deref().and_then(|action| {
                if action.is_empty() {
                    Some(base.to_string())
                } else if action.starts_with("//") {
                    Url::parse(&format!("https:{action}"))
                        .ok()
                        .map(|u| u.to_string())
                } else {
                    base.join(action).ok().map(|u| u.to_string())
                }
            });
            let controls = form
                .select(&control_selector)
                .map(|control| {
                    let name = control.value().attr("name").map(|s| s.to_owned());
                    let control_type = control_type(control);
                    let value_present = control.value().attr("value").is_some();
                    let value_redacted = value_present
                        && should_redact_control(name.as_deref(), control_type.as_str());
                    ExploreFormControl {
                        name,
                        control_type,
                        value_present,
                        value_redacted,
                    }
                })
                .collect::<Vec<_>>();
            Ok(ExploreForm {
                id: format!(
                    "fnv1a64:{}",
                    id::fnv1a64_hex(&format!(
                        "{final_url}\nform:{index}\nmethod:{method}\naction:{}",
                        action.as_deref().unwrap_or("")
                    ))
                ),
                method,
                action,
                absolute_action,
                submit_supported: false,
                controls,
            })
        })
        .collect()
}

fn control_type(control: ElementRef<'_>) -> String {
    match control.value().name() {
        "input" => control
            .value()
            .attr("type")
            .unwrap_or("text")
            .trim()
            .to_ascii_lowercase(),
        name => name.to_owned(),
    }
}

fn should_redact_control(name: Option<&str>, control_type: &str) -> bool {
    if matches!(control_type, "hidden" | "password") {
        return true;
    }
    let Some(name) = name else {
        return false;
    };
    let name = name.to_ascii_lowercase();
    [
        "token", "csrf", "session", "password", "passwd", "secret", "auth",
    ]
    .iter()
    .any(|needle| name.contains(needle))
}

fn blackboard_hints(url: &str) -> ExploreBlackboardHints {
    let Ok(url) = Url::parse(url) else {
        return ExploreBlackboardHints::default();
    };
    let mut hints = ExploreBlackboardHints::default();
    for (key, value) in url.query_pairs() {
        match key.as_ref() {
            "course_id" => hints.course_id = Some(value.to_string()),
            "content_id" => hints.content_id = Some(value.to_string()),
            _ => {}
        }
    }
    hints
}

fn is_text_like(content_type: Option<&str>) -> bool {
    let Some(content_type) = content_type else {
        return true;
    };
    let content_type = content_type.to_ascii_lowercase();
    content_type.starts_with("text/")
        || content_type.contains("html")
        || content_type.contains("xml")
        || content_type.contains("json")
}

fn header_to_string(value: Option<&http::HeaderValue>) -> Option<String> {
    value.and_then(|v| v.to_str().ok()).map(ToOwned::to_owned)
}

fn sanitize_href(raw: &str) -> String {
    let trimmed = raw.trim();
    if trimmed.to_ascii_lowercase().starts_with("data:") {
        return format!("data:<redacted:{} bytes>", trimmed.len());
    }
    truncate_chars(trimmed, MAX_HREF_CHARS).0
}

fn normalize_text(s: &str) -> String {
    s.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn truncate_chars(s: &str, max_chars: usize) -> (String, bool) {
    if max_chars == 0 {
        return (String::new(), !s.is_empty());
    }
    let mut iter = s.char_indices();
    for _ in 0..max_chars {
        if iter.next().is_none() {
            return (s.to_owned(), false);
        }
    }
    if let Some((idx, _)) = iter.next() {
        (s[..idx].to_owned(), true)
    } else {
        (s.to_owned(), false)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn visit_url_policy_accepts_relative_and_course_host() {
        assert_eq!(
            normalize_visit_url("/webapps/portal/execute/tabs/tabAction").unwrap(),
            "https://course.pku.edu.cn/webapps/portal/execute/tabs/tabAction"
        );
        assert_eq!(
            normalize_visit_url("https://course.pku.edu.cn/webapps/test").unwrap(),
            "https://course.pku.edu.cn/webapps/test"
        );
    }

    #[test]
    fn visit_url_policy_rejects_unsafe_targets() {
        for input in [
            "https://example.com/",
            "http://127.0.0.1/",
            "file:///etc/passwd",
            "data:text/html,hello",
            "javascript:alert(1)",
            "https://course.pku.edu.cn:8443/",
            "https://course.pku.edu.cn/webapps/login/?action=logout",
            "https://course.pku.edu.cn/webapps/assignment/uploadAssignment?action=newAttempt",
        ] {
            assert!(normalize_visit_url(input).is_err(), "{input} should fail");
        }
    }

    #[test]
    fn html_extraction_keeps_links_and_redacts_unsafe_href() {
        let html = r##"
            <html>
              <head><title> Demo </title><script>bad()</script></head>
              <body>
                <header>top nav</header>
                <h1>教学内容</h1>
                <p>Hello <b>world</b></p>
                <a href="/webapps/blackboard/content/listContent.jsp?course_id=_1_1&content_id=_2_1">folder</a>
                <a href="/webapps/login/?action=logout">logout</a>
                <a href="/bbcswebdav/pid-1-dt-content-rid-99_1/xid-99_1">lecture.pdf</a>
                <a href="javascript:alert(1)">expand</a>
                <a href="data:text/plain;base64,SGVsbG8=">inline</a>
                <form method="post" action="/webapps/assignment/uploadAssignment">
                  <input type="hidden" name="csrf_token" value="secret">
                  <input type="text" name="comment" value="ok">
                </form>
                <table><caption>成绩</caption><tr><th>A</th><td>10</td></tr></table>
              </body>
            </html>
        "##;
        let result = parse_explore_html(
            html,
            "https://course.pku.edu.cn/webapps/blackboard/content/listContent.jsp?course_id=_1_1&content_id=_2_1",
            ExploreVisitOptions::default(),
        )
        .unwrap();

        assert_eq!(result.title.as_deref(), Some("Demo"));
        assert!(result.main_text.contains("Hello world"));
        assert!(!result.main_text.contains("top nav"));
        assert_eq!(result.headings[0].text, "教学内容");
        assert_eq!(result.attachments.len(), 1);
        assert_eq!(result.attachments[0].name, "lecture.pdf");
        let js = result
            .links
            .iter()
            .find(|link| link.text == "expand")
            .unwrap();
        assert!(!js.visit_allowed);
        assert_eq!(js.reason.as_deref(), Some("non_http_scheme"));
        let logout = result
            .links
            .iter()
            .find(|link| link.text == "logout")
            .unwrap();
        assert!(!logout.visit_allowed);
        assert_eq!(logout.reason.as_deref(), Some("unsafe_get_action"));
        let data = result
            .links
            .iter()
            .find(|link| link.text == "inline")
            .unwrap();
        assert!(data.href.starts_with("data:<redacted:"));
        assert_eq!(result.forms.len(), 1);
        assert!(!result.forms[0].submit_supported);
        assert!(result.forms[0].controls[0].value_redacted);
        assert_eq!(result.tables[0].caption.as_deref(), Some("成绩"));
        assert_eq!(result.blackboard.course_id.as_deref(), Some("_1_1"));
        assert_eq!(result.blackboard.content_id.as_deref(), Some("_2_1"));
    }

    #[test]
    fn truncates_main_text() {
        let result = parse_explore_html(
            "<html><body><p>abcdef</p></body></html>",
            "https://course.pku.edu.cn/webapps/test",
            ExploreVisitOptions {
                max_chars: 3,
                max_links: 10,
                max_table_rows: 10,
            },
        )
        .unwrap();
        assert_eq!(result.main_text, "abc");
        assert!(result.text_truncated);
    }
}
