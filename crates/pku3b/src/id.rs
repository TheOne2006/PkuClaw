//! Stable external identifiers for pku3b JSON contracts.
//!
//! Do not use Rust's randomized/default hashers for IDs that PkuClaw stores.
//! When Blackboard does not expose a durable ID, this module uses a documented
//! fixed FNV-1a 64-bit fingerprint over explicit input fields.

/// Stable FNV-1a 64-bit fingerprint.
///
/// Algorithm: offset basis `0xcbf29ce484222325`, prime `0x100000001b3`,
/// byte-wise XOR then wrapping multiply. The input string must be assembled by
/// the caller from explicit fields and should include separators.
pub fn fnv1a64_hex(input: &str) -> String {
    let mut hash = 0xcbf2_9ce4_8422_2325u64;
    for byte in input.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    format!("{hash:016x}")
}

#[allow(dead_code)]
pub fn course(course_id: &str) -> String {
    course_id.to_owned()
}

pub fn course_content(course_id: &str, content_id: &str) -> String {
    format!("{course_id}:{content_id}")
}

pub fn assignment(course_id: &str, content_id: &str) -> String {
    course_content(course_id, content_id)
}

pub fn assignment_attempt(course_id: &str, content_id: &str, attempt_id: &str) -> String {
    format!("{course_id}:{content_id}:attempt:{attempt_id}")
}

pub fn assignment_submitted_file(
    course_id: &str,
    content_id: &str,
    attempt_id: &str,
    file_id: &str,
) -> String {
    format!("{course_id}:{content_id}:attempt:{attempt_id}:file:{file_id}")
}

pub fn announcement(course_id: &str, local_id: &str) -> String {
    format!("{course_id}:{local_id}")
}

pub fn grade(course_id: &str, item_id: &str) -> String {
    format!("{course_id}:{item_id}")
}

pub fn video(course_id: &str, title: &str, time: &str, source_url: &str) -> String {
    let fp = fnv1a64_hex(&format!(
        "course_id={course_id}\ntitle={title}\ntime={time}\nsource_url={source_url}"
    ));
    format!("{course_id}:video:{fp}")
}

pub fn attachment(course_id: &str, content_id: &str, href: &str) -> String {
    let rid = rid_or_href_fingerprint(href);
    format!("{course_id}:{content_id}:attachment:{rid}")
}

pub fn rid_or_href_fingerprint(href: &str) -> String {
    if let Some(rid) = extract_rid(href) {
        rid
    } else {
        format!("fnv1a64:{}", fnv1a64_hex(href))
    }
}

fn extract_rid(href: &str) -> Option<String> {
    for marker in ["rid-", "xid-"] {
        let start = href.find(marker)? + marker.len();
        let tail = &href[start..];
        let end = tail
            .char_indices()
            .find_map(|(idx, ch)| {
                (!(ch.is_ascii_alphanumeric() || ch == '_' || ch == '-')).then_some(idx)
            })
            .unwrap_or(tail.len());
        let rid = tail[..end].trim_matches('-');
        if !rid.is_empty() {
            return Some(rid.to_owned());
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fnv1a64_is_deterministic() {
        assert_eq!(fnv1a64_hex("pku3b"), fnv1a64_hex("pku3b"));
        assert_ne!(fnv1a64_hex("pku3b"), fnv1a64_hex("Pku3b"));
    }

    #[test]
    fn stable_ids_are_field_based() {
        assert_eq!(assignment("_98023_1", "_1608367_1"), "_98023_1:_1608367_1");
        assert_eq!(grade("_98023_1", "_425326_1"), "_98023_1:_425326_1");
        assert_eq!(
            assignment_submitted_file("_98023_1", "_1606017_1", "_3437236_1", "_3421682_1"),
            "_98023_1:_1606017_1:attempt:_3437236_1:file:_3421682_1"
        );
    }

    #[test]
    fn attachment_prefers_rid() {
        let href = "/bbcswebdav/pid-1596835-dt-content-rid-11935960_1/xid-11935960_1";
        assert_eq!(rid_or_href_fingerprint(href), "11935960_1");
    }
}
