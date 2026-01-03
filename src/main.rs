use kalosm::sound::*;

//$env:RUSTFLAGS="-L native=C:\Progra~1\NVIDIA~1\CUDA\v13.1\lib\x64"
//$env:NVCC_APPEND_FLAGS="-D_ALLOW_COMPILER_AND_STL_VERSION_MISMATCH"

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