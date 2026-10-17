# Box sync service: webhook, schedule and Sync now

Turn Box changes into review items, triggered three ways.

## Scope
Sync Lambda: compare current folder file versions with the last-seen versions in DynamoDB; for added/edited files call extraction; for deleted files retire their items; idempotent and safe to run concurrently (conditional writes). Triggers: (1) Box webhook route on API Gateway: verify BOX-SIGNATURE-PRIMARY/SECONDARY (HmacSHA256, keys in Secrets Manager), reply 2xx fast, dedupe on body id, then invoke sync asynchronously; (2) EventBridge Scheduler every minute; (3) "Sync now" API call. `kloop box webhook register|teardown` for the Halvard folder (check exact trigger names in Box's Create Webhooks guide).
Not in scope: extraction internals.

## Inputs
Box client, review/extraction task, Terraform foundation. https://developer.box.com/guides/webhooks/v2/

## Definition of Done
Unit tests for signature verification (valid, invalid, secondary key, duplicate) and change detection; deployed: a Box edit produces review items within 60 seconds.

## Verification
`make test`; after `make deploy`: edit a file in Box, then check the Sources screen or `kloop status`.
