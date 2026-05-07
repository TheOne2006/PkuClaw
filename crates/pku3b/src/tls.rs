//! TLS compatibility helpers.
//!
//! PKU Blackboard has, at least in May 2026, served `course.pku.edu.cn` with a
//! broken chain: the leaf is issued by `GlobalSign GCC R6 AlphaSSL CA 2025`, but
//! the server may omit that intermediate and send an older AlphaSSL intermediate
//! instead. Strict TLS clients then fail even though the leaf/root are otherwise
//! valid.
//!
//! We keep certificate validation enabled. The workaround is to augment the
//! process OpenSSL trust bundle with the missing GlobalSign intermediate before
//! the native TLS connector is built. This is not `danger_accept_invalid_certs`.

use std::{
    io::Write as _,
    path::{Path, PathBuf},
    sync::Once,
};

use anyhow::Context as _;

use crate::utils;

static INSTALL_PKU_CA_BUNDLE: Once = Once::new();

/// Install pku3b's augmented CA bundle for native-tls/OpenSSL users.
///
/// The function is process-local and best-effort. If the bundle cannot be
/// created, pku3b logs a warning and falls back to the system TLS behavior.
pub fn install_pku_tls_ca_bundle() {
    INSTALL_PKU_CA_BUNDLE.call_once(|| {
        if std::env::var_os("PKU3B_DISABLE_TLS_CA_BUNDLE").is_some() {
            log::info!("PKU3B_DISABLE_TLS_CA_BUNDLE set; not installing augmented TLS bundle");
            return;
        }
        if let Err(err) = install_pku_tls_ca_bundle_inner() {
            log::warn!("failed to install augmented PKU TLS CA bundle: {err:#}");
        }
    });
}

fn install_pku_tls_ca_bundle_inner() -> anyhow::Result<()> {
    let mut sources = Vec::new();
    if let Some(path) = std::env::var_os("SSL_CERT_FILE").map(PathBuf::from)
        && path.exists()
    {
        sources.push(path);
    }
    if sources.is_empty()
        && let Some(path) = default_system_ca_file()
    {
        sources.push(path);
    }

    let mut bundle = Vec::new();
    for source in &sources {
        append_file(&mut bundle, source)
            .with_context(|| format!("append system CA bundle {}", source.display()))?;
    }
    append_pem(
        &mut bundle,
        GLOBALSIGN_GCC_R6_ALPHASSL_CA_2025_PEM.as_bytes(),
    )?;

    let path = augmented_bundle_path();
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)
            .with_context(|| format!("create TLS cache dir {}", parent.display()))?;
    }
    std::fs::write(&path, &bundle)
        .with_context(|| format!("write augmented TLS CA bundle {}", path.display()))?;

    // Rust 2024 marks environment mutation unsafe because it can race with
    // other threads. pku3b calls this at HTTP-client construction time before
    // native-tls/OpenSSL creates a connector; all callers share the same value.
    unsafe {
        std::env::set_var("SSL_CERT_FILE", &path);
    }
    log::debug!(
        "using augmented PKU TLS CA bundle from {} ({} source files)",
        path.display(),
        sources.len()
    );
    Ok(())
}

fn augmented_bundle_path() -> PathBuf {
    utils::projectdir()
        .cache_dir()
        .join("tls")
        .join("pku3b-ca-bundle.pem")
}

fn default_system_ca_file() -> Option<PathBuf> {
    [
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/pki/tls/certs/ca-bundle.crt",
        "/etc/ssl/ca-bundle.pem",
        "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",
        "/etc/ssl/cert.pem",
    ]
    .into_iter()
    .map(PathBuf::from)
    .find(|path| path.exists())
}

fn append_file(bundle: &mut Vec<u8>, path: &Path) -> anyhow::Result<()> {
    let data = std::fs::read(path)?;
    append_pem(bundle, &data)
}

fn append_pem(bundle: &mut Vec<u8>, pem: &[u8]) -> anyhow::Result<()> {
    if !bundle.is_empty() && !bundle.ends_with(b"\n") {
        bundle.write_all(b"\n")?;
    }
    bundle.write_all(pem)?;
    if !bundle.ends_with(b"\n") {
        bundle.write_all(b"\n")?;
    }
    Ok(())
}

/// GlobalSign GCC R6 AlphaSSL CA 2025, downloaded from the CA issuer URL in
/// the Blackboard leaf certificate:
/// http://secure.globalsign.com/cacert/gsgccr6alphasslca2025.crt
///
/// Subject: C=BE, O=GlobalSign nv-sa, CN=GlobalSign GCC R6 AlphaSSL CA 2025
/// Issuer: OU=GlobalSign Root CA - R6, O=GlobalSign, CN=GlobalSign
/// Validity: 2025-05-21 to 2027-05-21.
const GLOBALSIGN_GCC_R6_ALPHASSL_CA_2025_PEM: &str = r#"-----BEGIN CERTIFICATE-----
MIIFjTCCA3WgAwIBAgIRAIN9TriekS/nLK07x2kt3CAwDQYJKoZIhvcNAQELBQAw
TDEgMB4GA1UECxMXR2xvYmFsU2lnbiBSb290IENBIC0gUjYxEzARBgNVBAoTCkds
b2JhbFNpZ24xEzARBgNVBAMTCkdsb2JhbFNpZ24wHhcNMjUwNTIxMDIzNjUyWhcN
MjcwNTIxMDAwMDAwWjBVMQswCQYDVQQGEwJCRTEZMBcGA1UEChMQR2xvYmFsU2ln
biBudi1zYTErMCkGA1UEAxMiR2xvYmFsU2lnbiBHQ0MgUjYgQWxwaGFTU0wgQ0Eg
MjAyNTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBAJ/oiu0Bviq52UUE
ADbFWmgu3rC7KDSMoorLN1Wd03McG3Z1aP71DlPCE33838r72Dfuj5M9LXfiQLJp
Au6MwNExmKOzothw4x0zGf5oBYyrCMGm3fBpLPafwYQ3MchBOWMTbf83rKUPLH48
KCJ0MnU8GUl8oA/J81wIvbbKPuNrFf6hvJDccjzc4NyxLz3A89zjV2g5whCg5O0u
9YX4Zxk9JHuc/LvllOJO4waAYLjbWBJkz3rV3ts1SmSYnJqmyRTIjXwQgRvhEYqt
DbRskt0W7M6cPwCze3GTBN2UHNpHkMs3YmVxku68I0aOQn5+uz//fDROP3z1Z/7I
APteRtECAwEAAaOCAV8wggFbMA4GA1UdDwEB/wQEAwIBhjAdBgNVHSUEFjAUBggr
BgEFBQcDAQYIKwYBBQUHAwIwEgYDVR0TAQH/BAgwBgEB/wIBADAdBgNVHQ4EFgQU
xbSTj28r3B5Iv7cQMIXO0bK7SC0wHwYDVR0jBBgwFoAUrmwFo5MT4qLn4tcc1sfw
f8hnU6AwewYIKwYBBQUHAQEEbzBtMC4GCCsGAQUFBzABhiJodHRwOi8vb2NzcDIu
Z2xvYmFsc2lnbi5jb20vcm9vdHI2MDsGCCsGAQUFBzAChi9odHRwOi8vc2VjdXJl
Lmdsb2JhbHNpZ24uY29tL2NhY2VydC9yb290LXI2LmNydDA2BgNVHR8ELzAtMCug
KaAnhiVodHRwOi8vY3JsLmdsb2JhbHNpZ24uY29tL3Jvb3QtcjYuY3JsMCEGA1Ud
IAQaMBgwCAYGZ4EMAQIBMAwGCisGAQQBoDIKAQMwDQYJKoZIhvcNAQELBQADggIB
AB/uvBuZf4CiuSahwiXn4geF52roAH+6jxsEPTXTfb7bbeMDXsYgRRsOTNA70ruZ
Tnz5DfFMuBhNoFhIFb0qR1izdy6VkdKOqFPNF2dOFI1EcnY9l2ory9mrzHqVbrL4
vzUd17FLUVyjTVU7PAv4nxyhnO1GTeT83YlrdRF31NyR6bvZVTEERHmpbWSgeveJ
LRtaMzlGWiLZ8IwkH7o6GH3jp/KPtDW4Npu8w64HrRZdN2pqQhi7+YKwfHM7H+2U
dM1BGN0sjOWMVbMSB9MtCsleS2Mb7TRZEbOHxECJLLIluQypZr7Pol3+hAqrhyKI
k+6y+Da0NeDuWxW59Ku4NvClqW1UFX1SpfNGhzVfp/CH+vPM1tySomx2jE0EnYZu
GwVucXPBsp5nUWqUV9+143glVuS7GTg9hFPjNBInn17HbCoIIQIOzj5Vd9bK3A9U
GxXNpwenDHEalCsD/4eQYDHPhFE7sNe0D/OXu+FAM02VZkARx37Jp4bDdujvgL9P
vZPR3wThvDN1CTU8Bc3xea3yKFAraKcPZLkhReQUAm2VpR+HSJRPlUpYizlF9WkL
h3KcAVCBJWvnOkVwxyU5QJMcnwW95JlOtx+9100GL99jHE5rs3gXp7F4bg8H01QT
9jVOhBBmQ7nQoXuwI0tqal2QUqZz3eeu62CU7xBwtfYR
-----END CERTIFICATE-----
"#;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bundled_intermediate_is_pem() {
        assert!(GLOBALSIGN_GCC_R6_ALPHASSL_CA_2025_PEM.contains("BEGIN CERTIFICATE"));
        assert!(GLOBALSIGN_GCC_R6_ALPHASSL_CA_2025_PEM.contains("END CERTIFICATE"));
    }

    #[test]
    fn append_pem_adds_newlines() {
        let mut bundle = b"abc".to_vec();
        append_pem(&mut bundle, b"def").unwrap();
        assert_eq!(bundle, b"abc\ndef\n");
    }

    #[test]
    fn augmented_bundle_path_is_stable() {
        let path = augmented_bundle_path();
        assert_eq!(
            path.file_name().and_then(|s| s.to_str()),
            Some("pku3b-ca-bundle.pem")
        );
    }
}
