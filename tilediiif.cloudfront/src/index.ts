import {
    canonicaliseRequestWithoutDimensions,
    formatRequest,
    parseRequest,
} from "./iiif-image-2.1";

export default function handler(
    event: AWSCloudFrontFunction.Event
): AWSCloudFrontFunction.Request | AWSCloudFrontFunction.Response {
    // The uri starts with a /, so ignore the first empty segment
    const segments = event.request.uri.split("/").slice(1);
    const req = parseRequest(segments);
    if (req === null) {
        const response: AWSCloudFrontFunction.Response = {
            statusCode: 404,
        };
        return response;
    }
    const canonicalReq = canonicaliseRequestWithoutDimensions(req);
    if (canonicalReq !== req) {
        const canonicalPath = `/${formatRequest(canonicalReq).join("/")}`;
        console.log(
            `Internal redirect from non-canonical: ${event.request.uri} to canonical: ${canonicalPath}`
        );
        event.request.uri = canonicalPath;
    }
    return event.request;
}
