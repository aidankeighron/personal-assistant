import sounddevice as sd

def list_audio_devices():
    print(f"\n{'Index':<6} {'Type':<8} {'Channels':<10} {'Device Name'}")
    print("-" * 80)
    
    devices = sd.query_devices()
    
    for index, device in enumerate(devices):
        # Determine if input, output, or both
        in_channels = device['max_input_channels']
        out_channels = device['max_output_channels']
        
        dev_type = ""
        if in_channels > 0 and out_channels > 0:
            dev_type = "In/Out"
        elif in_channels > 0:
            dev_type = "Input"
        elif out_channels > 0:
            dev_type = "Output"
        else:
            continue # Skip devices with 0 channels

        # Format channel info
        chan_info = f"{in_channels}in/{out_channels}out"
        
        print(f"{index:<6} {dev_type:<8} {chan_info:<10} {device['name']}")

    print("-" * 80)
    print("\nUse the 'Index' number in your LocalAudioTransportParams:")
    print("audio_in_index  = Index of your microphone")
    print("audio_out_index = Index of your speakers/headphones")

if __name__ == "__main__":
    try:
        list_audio_devices()
    except Exception as e:
        print(f"Error: {e}")
        print("Ensure 'sounddevice' is installed: pip install sounddevice")