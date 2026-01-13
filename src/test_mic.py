"""
Raw PyAudio test - bypasses Pipecat entirely to test if mic is working.
"""
import pyaudio
import struct
import math

# Configuration
AUDIO_INDEX = 1  # Your Logitech mic
SAMPLE_RATE = 16000
CHUNK_SIZE = 1024
FORMAT = pyaudio.paInt16

def get_volume(data):
    """Calculate RMS volume from audio data."""
    count = len(data) // 2
    shorts = struct.unpack(f"{count}h", data)
    sum_squares = sum(s * s for s in shorts)
    rms = math.sqrt(sum_squares / count) if count > 0 else 0
    return rms

def main():
    p = pyaudio.PyAudio()
    
    # Get device info
    info = p.get_device_info_by_index(AUDIO_INDEX)
    print(f"Testing device [{AUDIO_INDEX}]: {info['name']}")
    print(f"  Max input channels: {info['maxInputChannels']}")
    print(f"  Default sample rate: {info['defaultSampleRate']}")
    print()
    
    try:
        stream = p.open(
            format=FORMAT,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            input_device_index=AUDIO_INDEX,
            frames_per_buffer=CHUNK_SIZE
        )
        print(f"Stream opened successfully at {SAMPLE_RATE}Hz!")
        print("Listening for 10 seconds... Speak into the mic!")
        print("-" * 50)
        
        for i in range(int(SAMPLE_RATE / CHUNK_SIZE * 10)):  # 10 seconds
            data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            volume = get_volume(data)
            
            # Visual volume meter
            bar_len = int(volume / 500)
            bar = "#" * min(bar_len, 50)
            print(f"\rVolume: {volume:8.1f} |{bar:<50}|", end="", flush=True)
        
        print("\n\nTest complete!")
        stream.stop_stream()
        stream.close()
        
    except Exception as e:
        print(f"ERROR opening stream: {e}")
        print("\nTry a different sample rate or device index!")
    
    p.terminate()

if __name__ == "__main__":
    main()
