import numpy as np
from tensorflow.keras.models import load_model

model = load_model("skin_model.h5")

dummy = np.zeros((1, 224, 224, 3))
prediction = model.predict(dummy)

print("Prediction:", prediction)
print("Number of classes:", prediction.shape[1])