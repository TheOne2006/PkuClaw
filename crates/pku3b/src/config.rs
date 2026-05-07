use compio::fs;

#[derive(Debug, serde::Deserialize, serde::Serialize)]
pub struct Config {
    pub username: String,
    pub password: String,
}

pub async fn read_cfg(path: impl AsRef<std::path::Path>) -> anyhow::Result<Config> {
    let path = path.as_ref();
    if !path.exists() {
        anyhow::bail!("file not found");
    }
    let buffer = fs::read(path).await?;
    let content = String::from_utf8(buffer)?;
    let cfg: Config = toml::from_str(&content)?;
    Ok(cfg)
}

pub async fn write_cfg(path: impl AsRef<std::path::Path>, cfg: &Config) -> anyhow::Result<()> {
    let path = path.as_ref();
    if let Some(parent) = path.parent()
        && !parent.exists()
    {
        fs::create_dir_all(parent).await?;
    }
    let content = toml::to_string(cfg)?;
    fs::write(path, content).await.0?;
    Ok(())
}
