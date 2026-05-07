extern crate directories as dirs;

mod api;
mod cache;
mod cli;
mod config;
mod http;
mod id;
mod multipart;
mod qs;
mod tls;
mod utils;

use clap::Parser as _;
use shadow_rs::shadow;
shadow!(build);

#[compio::main]
async fn main() {
    env_logger::Builder::new()
        .filter_level(log::LevelFilter::Warn)
        .parse_default_env()
        .filter_module("selectors::matching", log::LevelFilter::Info)
        .filter_module("html5ever::tokenizer", log::LevelFilter::Info)
        .filter_module("html5ever::tree_builder", log::LevelFilter::Error)
        .init();

    let cli = match cli::Cli::try_parse() {
        Ok(cli) => cli,
        Err(err) => {
            let error = cli::clap_error_to_error(err);
            cli::print_error(error.clone(), false);
            std::process::exit(cli::exit_code(&error));
        }
    };
    let pretty = cli.pretty();

    if let Err(err) = cli::start(cli).await {
        let error = cli::anyhow_to_error(err);
        cli::print_error(error.clone(), pretty);
        std::process::exit(cli::exit_code(&error));
    }
}
