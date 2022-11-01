import { foo } from "./foo";

export default function handler(
    event: AWSCloudFrontFunction.Event
): AWSCloudFrontFunction.Request {
    var match = /(\w+)-.*\.(\w+)/.exec(event.request.uri);
    if (match) {
        event.request.uri = `/${match[1]}.${match[2]}`;
    }
    console.log(foo(3));
    return event.request;
}
