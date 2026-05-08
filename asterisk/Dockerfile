FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends asterisk \
    && mkdir -p /recordings \
    && rm -rf /var/lib/apt/lists/*

COPY config/ /etc/asterisk/

RUN chown -R asterisk:asterisk /etc/asterisk /var/lib/asterisk /var/log/asterisk /var/spool/asterisk /run/asterisk /recordings

EXPOSE 5060/udp 5038/tcp 10000-10020/udp

CMD ["asterisk", "-f", "-U", "asterisk", "-G", "asterisk", "-vvv"]
