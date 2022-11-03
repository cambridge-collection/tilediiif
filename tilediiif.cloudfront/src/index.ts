import {
    canonicaliseRequestWithoutDimensions,
    formatRegion,
    formatRequest,
    formatRotation,
    formatSize,
    ImageQuality,
    ImageRegionType,
    ImageRequestType,
    ImageSizeType,
    parseRequest,
} from "./iiif-image-2.1";

export default function handler(
    event: AWSCloudFrontFunction.Event
): AWSCloudFrontFunction.Request | AWSCloudFrontFunction.Response {
    // The uri starts with a /, so ignore the first empty segment
    const segments = event.request.uri.split("/").slice(1);
    const req = parseRequest(segments);
    if (req === null) {
        return response404();
    }
    const cReq = canonicaliseRequestWithoutDimensions(req);
    let resolvedPath: string;
    if (
        cReq.type === ImageRequestType.IMAGE &&
        cReq.region.type === ImageRegionType.ABSOLUTE &&
        cReq.size.type === ImageSizeType.ABSOLUTE &&
        cReq.rotation.degrees === 0 &&
        !cReq.rotation.mirrored &&
        cReq.quality === ImageQuality.DEFAULT &&
        cReq.format === "jpg"
    ) {
        // The key layout used for tiles in S3 is:
        // {identifier}/{region}-{size.w},-{rotation}-{quality}.{format}
        resolvedPath = `${cReq.identifier}/${formatRegion(
            cReq.region
        )}-${formatSize(cReq.size)}-${formatRotation(cReq.rotation)}-${
            cReq.quality
        }.${cReq.format}`;
    } else if (cReq.type === ImageRequestType.IMAGE_INFO) {
        resolvedPath = formatRequest(cReq).join("/");
    } else {
        return response404();
    }

    event.request.uri = `/${resolvedPath}`;
    return event.request;
}

function response404(): AWSCloudFrontFunction.Response {
    return {
        statusCode: 404,
        statusDescription: "Not Found",
        headers: { "access-control-allow-origin": { value: "*" } },
    };
}
