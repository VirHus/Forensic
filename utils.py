from pydub import AudioSegment
import os
import mimetypes

ALLOWED_AUDIO_EXTENSIONS = {"wav", "mp3"}
ALLOWED_DOC_EXTENSIONS = {"docx", "xlsx", "pdf", "pptx"}

def allowed_file(filename, allowed_extensions):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_extensions

def convert_to_wav(input_path):
    """ Converts MP3 to WAV if needed. """
    if input_path.lower().endswith(".wav"):
        return input_path  

    output_path = os.path.splitext(input_path)[0] + ".wav"  
    audio = AudioSegment.from_file(input_path, format="mp3")
    audio.export(output_path, format="wav")

    os.remove(input_path)  # Remove original MP3 file
    return output_path

def get_mime_type(file_path):
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type
