import matplotlib.pyplot as plt
import numpy as np
from scipy.io import wavfile
import os

def plot_waveforms(original_path, stego_path):
    orig_rate, orig_data = wavfile.read(original_path)
    stego_rate, stego_data = wavfile.read(stego_path)

    plt.figure(figsize=(10, 6))

    # Original
    plt.subplot(2, 1, 1)
    plt.plot(orig_data, color='navy')
    plt.title('Original Cover Audio')
    plt.ylabel('Amplitude')
    plt.xlabel('Time')

    # Stego
    plt.subplot(2, 1, 2)
    plt.plot(stego_data, color='darkred')
    plt.title('Stego-audio')
    plt.ylabel('Amplitude')
    plt.xlabel('Time')

    plot_path = os.path.join("static", "waveform_compare.png")
    plt.tight_layout()
    plt.savefig(plot_path)
    plt.close()
