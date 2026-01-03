use kalosm::sound::*;

#[tokio::main]
async fn main() -> Result<(), anyhow::Error> {
    println!("New Whisper...");
    let model = WhisperBuilder::default().with_source(WhisperSource::TinyEn).build().await?;
    
    println!("Getting Mic...");
    let mic = MicInput::default();
    println!("Getting Stream...");
    let stream = mic.stream();
    
    println!("Transcribing stream...");
    let mut text_stream = stream.transcribe(model);

    while let Some(segment) = text_stream.next().await {
        print!("{}", segment.text());
        use std::io::{self, Write};
        io::stdout().flush()?;
    }

    Ok(())
}