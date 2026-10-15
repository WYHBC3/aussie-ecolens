FROM public.ecr.aws/lambda/python:3.12

COPY backend/person3-tagging-lambda/requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt

RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY backend/person3-tagging-lambda/lambda_function.py ${LAMBDA_TASK_ROOT}/lambda_function.py
COPY AussieEcoLense/model.pt ${LAMBDA_TASK_ROOT}/model.pt
COPY AussieEcoLense/labels.txt ${LAMBDA_TASK_ROOT}/labels.txt

CMD ["lambda_function.lambda_handler"]
