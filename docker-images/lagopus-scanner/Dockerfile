FROM python:3-alpine

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN apk update && apk add postgresql-dev gcc python3-dev musl-dev
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD [ "python", "./scan.py" ]
