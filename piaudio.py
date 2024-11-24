import asyncio
import wave
import functools
import io
import numpy
import psutil, os
import time
import scipy.signal as signal
import pygame
import random
import glob
from sys import platform
if platform == "linux" or platform == "linux2":
    import alsaaudio
else:
    import pyaudio
from pydub import AudioSegment
from multiprocessing import Process, Value, Array, Queue, Manager

import common

# The min and max timeframe in seconds for
# the speed change to trigger, randomly selected
MIN_MUSIC_FAST_TIME = 4
MAX_MUSIC_FAST_TIME = 8
MIN_MUSIC_SLOW_TIME = 10
MAX_MUSIC_SLOW_TIME = 23

END_MIN_MUSIC_FAST_TIME = 6
END_MAX_MUSIC_FAST_TIME = 10
END_MIN_MUSIC_SLOW_TIME = 8
END_MAX_MUSIC_SLOW_TIME = 12

def win_audio_loop(fname,ratio,stop_proc):
    p = pyaudio.PyAudio()
    #define stream chunk
    chunk = 1024

    #open a wav format music
    while(True):
        if(stop_proc.value):
            pass
        elif(fname['song'] != ''):
            # print(fname['song'])
            f = wave.open(random.choice(glob.glob(fname['song'])))
            #instantiate PyAudio

            #open stream
            stream = p.open(format = p.get_format_from_width(f.getsampwidth()),
                            channels = f.getnchannels(),
                            rate = f.getframerate(),
                            output = True)


            # Resamples audio data at the rate given by 'ratio' above.
            def Resample(data):
                # for data in samples:
                array = numpy.fromstring(data, dtype=numpy.int16)
                # Split data into seperate channels and resample. Divide by two
                # since there are two channels. We round to the nearest multiple of
                # 32 as the resampling is more efficient the closer the sizes are to
                # being powers of two.
                num_output_frames = int(array.size / (ratio.value * 2)) & (~0x1f)
                reshapel = signal.resample(array[0::2], num_output_frames)
                reshaper = signal.resample(array[1::2], num_output_frames)

                final = numpy.ones((num_output_frames,2))
                final[:, 0] = reshapel
                final[:, 1] = reshaper

                out_data = final.flatten().astype(numpy.int16).tostring()
                return out_data
            #read data
            data = f.readframes(chunk)

            #play stream
            while data:
                stream.write(data)
                data = f.readframes(chunk)
                try:
                    if data:
                        data = Resample(data)
                except:
                    pass
                if stop_proc.value:
                    stream.stop_stream()
                    stream.close()
                    break



            #stop stream
            stream.stop_stream()
            stream.close()
            #
            # #close PyAudio
            # p.terminate()



def audio_loop(fname, ratio, stop_proc):
    # TODO: As a future improvment, we could precompute resampled versions of the track
    # at the "steady" playback rates, and only do dynamic resampling when transitioning
    # between them.
    PERIOD=1024 * 4
    # Two channels, two bytes per sample.
    PERIOD_BYTES = PERIOD * 2 * 2

    time.sleep(0.5)
    proc = psutil.Process(os.getpid())
    proc.nice(-5)
    time.sleep(0.02)
    wav_data = None



    song_loaded = False
    while(True):
        if(stop_proc.value == 1):
            pass
        elif(fname['song'] != ''):
            if(song_loaded == False):
                try:
                  random_song = random.choice(glob.glob(fname['song']))
                  segment = AudioSegment.from_file(random_song)
                except:
                  segment = AudioSegment.from_wav("audio/Joust/music/classical.wav")

                wav_data = io.BytesIO()
                segment.export(wav_data, 'wav')
                wav_data = wav_data.getbuffer()
                song_loaded = True
                continue
            elif(stop_proc.value == 0):
                wf = wave.open(io.BytesIO(wav_data), 'rb')
                if len(wf.readframes(1)) == 0:
                    raise ValueError("Empty WAV file played.")
                wf.rewind()
                
                device = alsaaudio.PCM(channels=wf.getnchannels(), rate=wf.getframerate(), \
                    format=alsaaudio.PCM_FORMAT_S16_LE, periodsize=PERIOD, device='default')

                # Loops samples of up to read_size bytes from the wav file.
                def ReadSamples(wf, read_size):
                    while True:
                        sample = wf.readframes(read_size)
                        if len(sample) > 0:
                            yield sample
                        else:
                            return
                            

                # Writes incoming samples in chunks of write_size to device.
                # Quits when stop_proc is set to a non-zero value.
                def WriteSamples(device, write_size, samples):
                    buf = bytearray()
                    for sample in samples:
                        buf.extend(sample)
                        while len(buf) >= write_size:
                            try:
                                device.write(buf[:write_size])
                            except alsaaudio.ALSAAudioError as e:
                                print("Error writing to ALSA device: {}".format(e))
                                break
                            del buf[:write_size]
                        if stop_proc.value:
                            return

                # Resamples audio data at the rate given by 'ratio' above.
                def Resample(samples):
                    for data in samples:
                        array = numpy.fromstring(data, dtype=numpy.int16)
                        # Split data into seperate channels and resample. Divide by two
                        # since there are two channels. We round to the nearest multiple of
                        # 32 as the resampling is more efficient the closer the sizes are to
                        # being powers of two.
                        num_output_frames = int(array.size / (ratio.value * 2)) & (~0x1f)
                        reshapel = signal.resample(array[0::2], num_output_frames)
                        reshaper = signal.resample(array[1::2], num_output_frames)

                        final = numpy.ones((num_output_frames,2))
                        final[:, 0] = reshapel
                        final[:, 1] = reshaper

                        out_data = final.flatten().astype(numpy.int16).tostring()
                        yield out_data
                     
                WriteSamples(device, PERIOD_BYTES, Resample(ReadSamples(wf, PERIOD)))
                wf.close()
                device.close()
                song_loaded = False

@functools.lru_cache(maxsize=128)
class Audio:
    def __init__(self, fname):
        #these are probably not necessary
        #segment = AudioSegment.from_file(fname)
        #buf = io.BytesIO()
        #segment.export(buf, 'wav')
        #buf.seek(0)
        pygame.mixer.init()
        self.sample_ = pygame.mixer.Sound(file=fname)
        self.fname_ = fname

    #this will not work for files other than wav at the moment
    def start_effect(self):
        self.sample_.play()

    def stop_effect(self):
        self.sample_.stop()

    def start_effect_music(self):
        self.sample_.play(-1)

    def stop_effect_music(self):
        self.sample_.stop()

    def get_length_secs(self):
        return self.sample_.get_length()

    def start_effect_and_wait(self):
        self.start_effect()
        time.sleep(self.get_length_secs())

@functools.lru_cache(maxsize=16)
class Music:
    def __init__(self, name):
        self.name = name
        self.transition_future_ = asyncio.Future()

        self.stop_proc = Value('i', 1)
        self.ratio = Value('d' , 1.0)
        manager = Manager()
        self.fname = manager.dict()
        self.fname['song'] = ''
        if platform == "linux" or platform == "linux2":
            self.t = Process(target=audio_loop, args=(self.fname, self.ratio, self.stop_proc))
        elif "win" in platform:
            self.t = Process(target=win_audio_loop, args=(self.fname, self.ratio, self.stop_proc))
        self.t.start()


    def load_audio(self, fname):
        self.fname['song'] = fname

    def start_audio_loop(self):
        self.stop_proc.value = 0

    def stop_audio(self):
        self.stop_proc.value = 1
        self.fname['song'] = ''
        time.sleep(0.1)
        self.transition_future_.cancel()

    def change_ratio(self, ratio):
        self.ratio.value = ratio

    def transition_ratio(self, new_ratio, transition_duration=1.0):
        """Smoothly transitions between the current sampling ratio and the given one.
           Returns a task that completes once the transition is finished."""
        async def do_transition():
            num_steps = 20
            old_ratio = self.ratio.value
            for i in range(num_steps):
                t = (i+1) / 20
                ratio = common.lerp(old_ratio, new_ratio, t)
                ratio = old_ratio * (1-t) + new_ratio * t
                self.change_ratio(ratio)
                await asyncio.sleep(transition_duration / num_steps)

        self.transition_future_.cancel()
        self.transition_future_ = asyncio.ensure_future(do_transition())
        return self.transition_future_

class DummyMusic:
    def start_audio_loop(self): pass
    def stop_audio(self): pass
    def change_ratio(self): pass
    def transition_ratio(self, new_ratio, transition_duration=None):
        async def do_nothing(): pass
        return asyncio.ensure_future(do_nothing())

def InitAudio():
    pygame.mixer.init(47000, -16, 2 , 4096)
