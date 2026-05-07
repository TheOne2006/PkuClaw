pub mod builder;
pub mod low_level;

use anyhow::Context;
pub use builder::ClientBuilder;
use chrono::TimeZone;
use cyper::IntoUrl;
use itertools::Itertools;
use scraper::Selector;
use std::{
    collections::{HashMap, HashSet},
    hash::{Hash, Hasher},
    str::FromStr,
    sync::Arc,
};

use crate::{
    multipart, qs,
    utils::{with_cache, with_cache_bytes},
};

struct ClientInner {
    http_client: low_level::LowLevelClient,
    cache_ttl: Option<std::time::Duration>,
    download_artifact_ttl: Option<std::time::Duration>,
    cookie_restore_path: Option<std::path::PathBuf>,
}

impl std::fmt::Debug for ClientInner {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ClientInner")
            .field("cache_ttl", &self.cache_ttl)
            .field("download_artifact_ttl", &self.download_artifact_ttl)
            .finish()
    }
}

#[derive(Debug, Clone)]
pub struct Client(Arc<ClientInner>);

impl std::ops::Deref for Client {
    type Target = low_level::LowLevelClient;

    fn deref(&self) -> &Self::Target {
        &self.0.http_client
    }
}

impl Client {
    pub fn builder() -> ClientBuilder {
        ClientBuilder::default()
    }

    pub fn cache_ttl(&self) -> Option<&std::time::Duration> {
        self.0.cache_ttl.as_ref()
    }

    pub fn download_artifact_ttl(&self) -> Option<std::time::Duration> {
        self.0.download_artifact_ttl
    }

    pub async fn save_cookies(&self) -> anyhow::Result<bool> {
        let Some(path) = &self.0.cookie_restore_path else {
            return Ok(false);
        };
        self.0.http_client.save_set_cookies(path).await?;
        Ok(true)
    }
}

pub mod blackboard;
pub mod portal;
