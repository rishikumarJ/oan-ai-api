import numpy as np
from loguru import logger
from pipecat.audio.filters.base_audio_filter import BaseAudioFilter
from pipecat.frames.frames import FilterControlFrame, FilterEnableFrame


class DeepFilterNetFilter(BaseAudioFilter):
    """Audio filter using DeepFilterNet3 for superior noise suppression."""
    
    def __init__(self, post_filter: bool = True):
        """
        Initialize the DeepFilterNet noise suppression filter.
        
        Args:
            post_filter: If True, applies additional attenuation to very noisy sections.
        """
        self._filtering = True
        self._sample_rate = 0
        self._model = None
        self._df_state = None
        self._post_filter = post_filter
        self._enhance = None
        
    async def start(self, sample_rate: int):
        """Initialize the filter with the transport's sample rate."""
        self._sample_rate = sample_rate
        try:
            from df.enhance import enhance, init_df
            
            # Initialize DeepFilterNet3 model
            # init_df returns (model, df_state, encoder) - we need first two
            self._model, self._df_state, _ = init_df(post_filter=self._post_filter)
            self._enhance = enhance
            
            # DeepFilterNet works at 48kHz internally, will resample if needed
            df_sr = self._df_state.sr()
            logger.info(f"✅ DeepFilterNet initialized (input_rate={sample_rate}, df_rate={df_sr})")
        except ImportError as e:
            logger.error(f"DeepFilterNet import failed: {e}")
            logger.error("Install with: pip install deepfilternet deepfilterlib")
            self._model = None
        except Exception as e:
            logger.error(f"DeepFilterNet init error: {e}")
            self._model = None
    
    async def stop(self):
        """Clean up the filter when stopping."""
        self._model = None
        self._df_state = None
        self._enhance = None
        
    async def process_frame(self, frame: FilterControlFrame):
        """Process control frames to enable/disable filtering."""
        if isinstance(frame, FilterEnableFrame):
            self._filtering = frame.enable
            logger.info(f"DeepFilterNet filtering {'enabled' if self._filtering else 'disabled'}")
            
    async def filter(self, audio: bytes) -> bytes:
        """Apply DeepFilterNet noise suppression to audio data."""
        if not self._filtering or self._model is None:
            return audio
            
        try:
            import torch
            
            # Convert bytes to float32 numpy array (int16 -> float32)
            audio_int16 = np.frombuffer(audio, dtype=np.int16)
            audio_float = audio_int16.astype(np.float32) / 32768.0
            
            # DeepFilterNet expects tensor with shape [batch, channels, time] or [channels, time]
            # Our audio is mono, so shape is [1, time]
            audio_tensor = torch.from_numpy(audio_float).unsqueeze(0)  # [1, T]
            
            # Enhance the audio
            enhanced_tensor = self._enhance(
                self._model, 
                self._df_state, 
                audio_tensor
            )
            
            # Convert back to numpy
            enhanced = enhanced_tensor.squeeze(0).numpy()
            
            # Convert back to int16 bytes
            enhanced_int16 = (enhanced * 32768.0).clip(-32768, 32767).astype(np.int16)
            return enhanced_int16.tobytes()
            
        except Exception as e:
            logger.debug(f"DeepFilterNet processing error: {e}, passing through original")
            return audio
