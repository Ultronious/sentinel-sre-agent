FROM public.ecr.aws/lambda/python:3.12

WORKDIR ${LAMBDA_TASK_ROOT}

COPY lambda/requirements.txt .

RUN pip install \
    --no-cache-dir \
    -r requirements.txt \
    -t ${LAMBDA_TASK_ROOT}

COPY agent/ ${LAMBDA_TASK_ROOT}/agent/

CMD ["agent.event_handler.lambda_handler"]