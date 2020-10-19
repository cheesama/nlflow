from fastapi import FastAPI

from nlu_flow.preprocessor.text_preprocessor import normalize

import dill

app = FastAPI()
is_ready = False

#load scenario_classifer_model
model = None
with open('./scenario_classifier_model.svc', 'rb') as f:
    model = dill.load(f)
    print ('scenario_classifier_model load success')

if model:
    is_ready = True

#endpoints
@app.get("/")
async def health():
    if is_ready:
        output = {'code': 200}
    else:
        output = {'code': 500}
    return output

@app.post("/predict")
async def predict_scenario(text: str):
    name = model.predict([normalize(text)])[0]
    confidence = model.predict_proba([normalize(text)])[0].max()

    return {'name': name, 'confidence': confidence, 'classifier': 'scenario_classifier_model.svc'}

