import os
import json
import base64
from backend.data_store import WebhookProcessor

def lambda_handler(event, context):
    processor = WebhookProcessor(os.environ['WEBHOOK_SECRET'])
    headers = {k.lower(): v for k, v in event['headers'].items()}
    # Handle base64 encoding (API Gateway can send body as base64)
    if event.get('isBase64Encoded'):
        raw_body = base64.b64decode(event['body'])
    else:
        raw_body = event['body'].encode('utf-8')
    try:
        payload = json.loads(raw_body)
    except Exception:
        return {'statusCode': 400, 'body': json.dumps({'error': 'Invalid JSON'})}
    if processor.verify_signature(headers, raw_body):
        try:
            success = processor.process(headers, payload)
            return {
                'statusCode': 200 if success else 500,
                'body': json.dumps({'status': 'Processed' if success else 'Processing failed'})
            }
        except Exception as e:
            return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}
    return {'statusCode': 401, 'body': json.dumps({'error': 'Invalid signature'})}