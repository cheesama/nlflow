from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from sklearn.pipeline import make_pipeline, Pipeline
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.svm import SVC
from sklearn.ensemble import RandomForestClassifier, AdaBoostClassifier
from sklearn.model_selection import GridSearchCV

from tqdm import tqdm
from pprint import pprint

from nlu_flow.utils import meta_db_client
from nlu_flow.preprocessor.text_preprocessor import normalize

import os, sys
import dill
import random

def train_faq_classifier():
    # load dataset
    utterances = []
    labels = []
    response_dict = {}

    ## get synonym data for data augmentation(for FAQ data augmentation)
    synonyms = []
    synonym_data = meta_db_client.get("meta-entities")
    for data in tqdm(
        synonym_data, desc=f"collecting synonym data for data augmentation ..."
    ):
        if type(data) != dict:
            print(f"check data type : {data}")
            continue

        synonyms.append(
            [
                normalize(each_synonym.get("synonym"))
                for each_synonym in data.get("meta_synonyms")
            ]
            + [normalize(data.get("Entity_Value"))]
        )

    faq_data = meta_db_client.get("nlu-faq-questions")
    for data in tqdm(faq_data, desc=f"collecting faq data ... "):
        if data["faq_intent"] is None or len(data["faq_intent"]) < 2:
            print(f"check data! : {data}")
            continue

        # assume same faq_intent questions have same answers set
        response_dict[data["faq_intent"]] = {
            "prompt_id": data.get("prompt_id", ""),
            "answer": data.get("answer", ""),
            "buttons": data.get("buttons", {}),
        }

        target_utterance = normalize(data["question"])

        # check synonym is included
        for synonym_list in synonyms:
            for i, prev_value in enumerate(synonym_list):
                if prev_value in target_utterance:
                    for j, post_value in enumerate(synonym_list):
                        if i == j:
                            continue
                        utterances.append(
                            target_utterance.replace(prev_value, post_value)
                        )
                        labels.append(data["faq_intent"])
                    break

        utterances.append(normalize(data["question"]))
        labels.append(data["faq_intent"])

    scenario_data = meta_db_client.get("nlu-intent-entity-utterances")
    for data in tqdm(random.choices(scenario_data, k=len(response_dict)), desc=f"collecting scenario data ... "):
        utterances.append(normalize(data["utterance"]))
        labels.append('시나리오')
    
    print(f"dataset num: {len(utterances)}")

    X_train, X_test, y_train, y_test = train_test_split(
        utterances, labels, random_state=88, test_size=0.1
    )

    pipe = Pipeline(steps=[('vectorize', TfidfVectorizer(analyzer="char_wb", ngram_range=(1,6))), ('svc', SVC(probability=True))])
    print("faq classifier training(with SVC)")
    
    # Parameter Grid
    param_grid = {'svc__C': [0.1, 1, 10, 100], 'svc__gamma': [1, 0.1, 0.01, 0.001, 0.00001, 10]}

    # Make grid search classifier
    clf_grid = GridSearchCV(pipe, param_grid, verbose=1)

    # Train the classifier
    clf_grid.fit(X_train, y_train)

    print("Best Parameters:\n", clf_grid.best_params_)
    print("Best Estimators:\n", clf_grid.best_estimator_)
    svc = clf_grid.best_estimator_()

    print("model training done, validation reporting")
    y_pred = svc.predict(X_test)
    print(classification_report(y_test, y_pred))

    reportDict = {}
    for k, v in classification_report(y_test, y_pred, output_dict=True).items():
        if "avg" in k:
            reportDict[k] = v

    with open("report.md", "w") as reportFile:
        print("faq classification result\n", file=reportFile)
        print(reportDict, file=reportFile)

    # save faq classifier model
    with open("faq_classifier_model.svc", "wb") as f:
        dill.dump(svc, f)
        print("faq_classifier model saved : faq_classifier_model.svc")

    # save faq response dict
    with open("faq_response_dict.dill", "wb") as f:
        dill.dump(response_dict, f)
        print("faq response data saved : faq_response_dict.dill")


train_faq_classifier()
