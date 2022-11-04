import boto3
import json

from tilediiif.tools.infojson import main as infojson
from tilediiif.tools.tilelayout import main as iiif_tiles
from tilediiif.tools.dzi_generation_faulthandler import run_dzi_generation_with_faulthandler_enabled as dzi_tiles


# TODO: pass the tiff path into the dzi_tiles function to generate the dzi tiles
# TODO: pass the dzi tiles into the iiif_tiles function to convert the tiles to iiif format
# TODO: write the generated tiles into the second s3 bucket

def lambda_handler(event, context):
    for record in event['Records']:
        if "s3:TestEvent" in str(record):
            print("This is a test event, skipping")
            continue
        body = json.loads(record["body"])
        print(body)

        # TODO: use boto3 to get the tif
        s3 = boto3.client('s3')
        key = body["Records"][0]["s3"]["object"]["key"]
        bucket = body["Records"][0]["s3"]["bucket"]["name"]
        response = s3.get_object(
            Bucket=bucket,
            Key=key
        )
        filestream = response["Body"]


