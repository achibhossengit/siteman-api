# Key Concepts & Definitions

* **What is an API?**: An API acts as a contract—a formal agreement of interaction between a client and a server.
* **API Design**: The intentional process of defining endpoints, methods, and resources in a standardized format before writing code. It is a critical decision-making phase that ensures the system is intuitive and user-friendly.
* **API-First Approach**: Prioritizing the design phase allows for better documentation, automated testing, and parallel development across different teams, even before the backend is fully implemented.

## Lifecycle of an API

An API is not just code; it follows a structured lifecycle to ensure scalability:

1. **Design**: Using standards like OpenAPI to create a contract understood by both humans and machines.
2. **Develop**: Implementation follows the established specifications, reducing errors and technical debt.
3. **Mock & Test**: Validating assumptions early using mock servers to catch design flaws before full deployment.
4. **Document**: Providing high-quality, human-readable documentation that explains the *why* behind fields, parameters, and logic.

## The Six Constraints of REST

To be considered truly "RESTful," an API must adhere to these six architectural constraints:

1. **Client-Server**: Decoupling the interface (client) from the data/logic (server) to allow independent evolution.
2. **Statelessness**: Every request must contain all information necessary for the server to fulfill it, without relying on stored session states on the server.
3. **Cacheability**: Responses must define their cacheability to improve performance and scalability.
4. **Uniform Interface**:
    * Resource Identification Through URIs
    * Standard HTTP methods
      > `GET /api/v1/users/10`


    * Send/receive (request payload/response) resource representations (JSON/XML).
      ```json
      {
        "id": 10,
        "name": "Rahim",
        "email": "rahim@example.com"
      }

      ```
    * Self-Descriptive Messages
    * Consistent Resource Naming convention
    * Hypermedia (HATEOAS)


5. **Layered System**: Allowing intermediary components like proxies and gateways to improve security and scalability without the client's knowledge.
6. **Code-On-Demand (Optional)**: The server can optionally provide executable code to the client.

## HATEOAS and Maturity

* **HATEOAS (Hypermedia as the Engine of Application State)**: A critical part of the uniform interface where the API provides hypermedia links in its responses, guiding the client through state transitions and making the API discoverable.
* **Richardson Maturity Model**: A scale to measure the "RESTfulness" of an API:
* **Level 0**: The "Swamp of POX" (Plain Old XML/JSON) often using a single endpoint.
* **Level 1**: Introduction of resource identification using URIs.
* **Level 2**: Proper use of HTTP verbs (GET, POST, PUT, DELETE) and status codes.
* **Level 3**: Full implementation of HATEOAS, making the API truly discoverable.



---

# Core Architectural Concepts

## 1. Partial Responses

A strategy to reduce bandwidth and latency by allowing clients to **request only the specific fields** necessary for their application, rather than the entire data object.

### Query Parameter Precision

Techniques for utilizing query parameters (such as **filtering, sorting, and pagination**) to enable precise, on-demand data retrieval, which is essential for handling large datasets efficiently.

### Error Handling

Best practices for constructing meaningful, user-friendly, and informative API error messages. This includes handling server-side exceptions gracefully to ensure stability without exposing sensitive internal information.

### HTTP Caching

A comprehensive guide to implementing Cache-Control headers. The session explains how to use directives like `public`, `private`, and `no-store` to control how data is cached across browsers and intermediary proxies.

### ETag Headers

An explanation of Entity Tags (ETags) as a mechanism for cache validation. By comparing ETags, the server can instruct the client to use previously cached data, significantly reducing redundant data transfers.

### API Versioning

Strategies for managing evolution in APIs. The session distinguishes between breaking changes (which require a new version to avoid disrupting existing clients) and non-breaking changes (which can be introduced incrementally).

## 2. Key Takeaways & Best Practices

* **Backward Compatibility**: Maintaining support for existing clients is prioritized. When breaking changes are unavoidable, implementing versioning (via URL or header-based approaches) allows for a transition period.
* **Graceful Depreciation**: When retiring older API versions, it is critical to provide clear warning notifications, migration guides, and adequate documentation to help users switch to newer versions.
* **Architectural Rigor**: The session emphasizes that API design is not just about coding, but about making strategic architectural decisions—such as choosing the right versioning strategy or caching policy—to ensure the longevity and reliability of the API.