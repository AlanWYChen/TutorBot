# ADR 0002: Verified identity and student scope

Status: accepted for P0-02.

Use the Firebase Admin SDK to verify bearer ID tokens (project/audience/issuer,
expiry/signature and revocation). Roles come from privileged Firebase custom
claims, checked against the current user record so removed admin permissions
cannot survive in a stale token. Unknown roles fail closed; missing role means
student. Request headers, query parameters and body values never select identity.

Production is the default mode. Emulator configuration is explicitly permitted
only in local/test mode with a demo project; startup fails if production has an
emulator host. Unsigned emulator tokens are a development-only Firebase behavior;
local tests are not proof of production cryptographic authentication.

Introduce only the users/student_accounts auth migration here. P0-04 extends
these tables with curriculum and learning-domain schemas. PostgreSQL repository
instances bind a verified principal once; every account lookup includes that
principal's owner predicate. Non-owned IDs return 404, without confirming existence.
DB grants/RLS are P0-03; no global knowledge routes or student uploads exist yet.

The web uses Firebase in-memory sessions and a same-origin, fixed-route API
proxy. Tokens travel in Authorization headers, never URLs/cookies/logs. Auth
errors are generic. Maintainer claims cannot be edited through the application.
A demo-only, guarded CLI provisions synthetic local accounts; production admin
provisioning remains a privileged operational procedure.

References:
- https://firebase.google.com/docs/auth/admin/verify-id-tokens
- https://firebase.google.com/docs/auth/admin/custom-claims
- https://firebase.google.com/docs/emulator-suite/connect_auth

The current Firebase client SDK requires Node 24.12+. Pin that runtime in
web/emulator images and CI. Pin the patched gRPC transitive dependency via npm
override; no Firestore functionality is used by TutorBot.
