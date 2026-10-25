# GitHub OAuth permissions

The current OAuth authorization request uses the OAuth App scopes `repo read:user`.

- `repo` grants broad repository access, including read and write access to private repositories. It is broader than read-only repository browsing, but it is retained because InternSim currently needs access to private assignment repositories. Do not replace it with a narrower scope until the product's private-repository workflow and required write operations have been verified.
- `read:user` grants access to the user's profile information. The integration uses this to identify the linked GitHub account.

For a least-privilege redesign, first enumerate the operations InternSim actually performs. If it only lists and reads repositories, consider a GitHub App with read-only installation permissions for repository metadata and contents. If it writes assignment changes or creates pull requests, grant only the required write permissions (for example, Contents and Pull requests) and restrict installation access to selected repositories where feasible.

A GitHub App is a separate integration configuration: it requires an App registration, installation flow, App credentials/private key, and installation-token handling. GitHub App installation permissions are not equivalent to OAuth App scopes. This recommendation does not change the current OAuth scopes or existing configuration.
