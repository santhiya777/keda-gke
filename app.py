import os
import time
import pika

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
QUEUE_NAME = os.getenv("QUEUE_NAME", "keda-demo-queue")

while True:
    try:
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=RABBITMQ_HOST)
        )

        channel = connection.channel()

        channel.queue_declare(
            queue=QUEUE_NAME,
            durable=True
        )

        print(f"Listening on queue: {QUEUE_NAME}", flush=True)

        while True:
            method, properties, body = channel.basic_get(
                queue=QUEUE_NAME,
                auto_ack=False
            )

            if body:
                print(
                    f"[{os.getenv('HOSTNAME', 'local')}] "
                    f"Received: {body.decode()}",
                    flush=True
                )

                time.sleep(2)

                channel.basic_ack(method.delivery_tag)
            else:
                time.sleep(1)

    except Exception as e:
        print(f"RabbitMQ connection error: {e}", flush=True)
        time.sleep(5)
