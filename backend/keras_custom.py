# backend/keras_custom.py

from typing import Dict, Any as _Any, Optional
import tensorflow as tf
from tensorflow.keras.layers import Layer, Masking as KerasMasking # type: ignore
from tensorflow.keras.initializers import Initializer # type: ignore
from tensorflow.keras import backend as K # type: ignore

class Any(Layer):
    def __init__(self, name: Optional[str] = None, **kwargs):
        
        super().__init__(name=name, **kwargs)

    def call(self, inputs, **kwargs):
        return inputs

    def get_config(self):
        cfg = super().get_config()
        return cfg

    @classmethod
    def from_config(cls, config):
        
        name = config.get("name", None)
        
        return cls(name=name)


class NotEqual(Layer):

    def __init__(self, value: Optional[float] = None, name: Optional[str] = None, **kwargs):
        
        super().__init__(name=name, **kwargs)
        self.value = value

    def call(self, inputs, **kwargs):
        try:
            # If two inputs provided, compare them
            if isinstance(inputs, (list, tuple)) and len(inputs) >= 2:
                a = tf.convert_to_tensor(inputs[0])
                b = tf.convert_to_tensor(inputs[1])
                out = tf.not_equal(a, b)
                return tf.cast(out, tf.float32)
            # Otherwise compare input to configured value (if present)
            x = tf.convert_to_tensor(inputs)
            if self.value is not None:
                cmp_val = tf.cast(tf.constant(self.value), x.dtype)
                out = tf.not_equal(x, cmp_val)
                return tf.cast(out, tf.float32)
            # fallback: return zeros of same shape
            return tf.zeros_like(tf.cast(x, tf.float32))
        except Exception:
            # very safe fallback: scalar zero
            try:
                return tf.zeros_like(tf.cast(tf.convert_to_tensor(inputs), tf.float32))
            except Exception:
                return tf.constant(0.0, dtype=tf.float32)

    def get_config(self):
        cfg = super().get_config()
        cfg.update({"value": self.value})
        return cfg

    @classmethod
    def from_config(cls, config):
        # Keras passes config as dict; extract 'value' if present
        value = config.get("value", None)
        name = config.get("name", None)
        return cls(value=value, name=name)

# ---------- Masking wrapper ----------
class MaskingPlaceholder(KerasMasking):
    def __init__(self, mask_value=None, name: Optional[str] = None, **kwargs):
        super().__init__(mask_value=mask_value, name=name, **kwargs)

    @classmethod
    def from_config(cls, config):
        return cls(mask_value=config.get("mask_value", None), name=config.get("name", None))

# ---------- Initializer placeholders ----------
class OnesInit(Initializer):
    def __call__(self, shape, dtype=None):
        return tf.ones(shape, dtype=dtype or tf.float32)
    def get_config(self):
        return {}

class ZerosInit(Initializer):
    def __call__(self, shape, dtype=None):
        return tf.zeros(shape, dtype=dtype or tf.float32)
    def get_config(self):
        return {}

class OrthogonalInit(Initializer):
    def __init__(self, gain=1.0):
        self.gain = gain
    def __call__(self, shape, dtype=None):
        return tf.keras.initializers.Orthogonal(gain=self.gain)(shape, dtype=dtype)
    def get_config(self):
        return {"gain": self.gain}

# ---------- DTypePolicy placeholder ----------
class DTypePolicy:
    def __init__(self, name: Optional[str] = None, compute_dtype: Optional[str] = None, variable_dtype: Optional[str] = None):
        self.name = name or "float32"
        self.compute_dtype = compute_dtype or "float32"
        self.variable_dtype = variable_dtype or "float32"

    @classmethod
    def from_config(cls, cfg):
        if isinstance(cfg, dict):
            return cls(name=cfg.get("name"), compute_dtype=cfg.get("compute_dtype"), variable_dtype=cfg.get("variable_dtype"))
        if isinstance(cfg, str):
            return cls(name=cfg)
        return cls()

    def get_config(self):
        return {"name": self.name, "compute_dtype": self.compute_dtype, "variable_dtype": self.variable_dtype}

# ---------- Utility: mapping ----------
def get_custom_objects() -> Dict[str, _Any]:
    """
    Provide mapping for Keras `custom_objects`.
    Add names here if inspect_h5_model reports additional unknown classes.
    """
    return {
        "Any": Any,
        "NotEqual": NotEqual,
        "Masking": MaskingPlaceholder,
        "Ones": OnesInit,
        "Zeros": ZerosInit,
        "Orthogonal": OrthogonalInit,
        "DTypePolicy": DTypePolicy,
    }