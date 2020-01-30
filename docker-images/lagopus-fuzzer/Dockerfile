FROM qlyoung/fuzzbox:latest

RUN apt-get install -yqq zip unzip sysstat libcap2 gdb python3 python3-setuptools jq
RUN git clone https://github.com/jfoote/exploitable.git && cd exploitable && python3 setup.py install

COPY entrypoint.sh /entrypoint.sh

ENTRYPOINT [ "/entrypoint.sh" ]
