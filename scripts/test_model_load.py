# scripts/test_model_load.py
import os, traceback
from tensorflow import keras
import numpy as np

# <- ADJUST path to the model we found
p = "..\data\mouse_lstm.keras"

print("testing model path:", p)
print("exists:", os.path.exists(p))
if os.path.exists(p):
    print("size:", os.path.getsize(p), "bytes")

try:
    print("loading model...")
    m = keras.models.load_model(p)
    print("model loaded OK:", type(m), "— summary (first layers):")
    try:
        m.summary()
    except Exception:
        print("(summary failed - still ok if model is custom)")
    # prepare a dummy input — change dims if your model expects different
    dummy = np.zeros((1, 8, 9), dtype=float)
    out = m.predict(dummy)
    print("predict output shape:", getattr(out, "shape", None))
    print("predict sample output:", out)
except Exception:
    print("model load/predict failed:")
    traceback.print_exc()