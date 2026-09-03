# PyPI Client

## Purpose

Compatag retrieves published distribution information from PyPI through the
standard JSON Simple Repository API.

The PyPI client is a data-access layer. It does not decide whether a
distribution is compatible with a deployment target.

## Endpoint

Compatag requests:

```text
GET https://pypi.org/simple/<normalized-project-name>/
Accept: application/vnd.pypi.simple.v1+json
```

Project names are normalized using PyPA's packaging utilities before the request is made.

## Data flow

```
PyPI Simple JSON
|
v
private wire models
|
v
normalization
|
v
ProjectDistributions
|
+-- DistributionFile
+-- DistributionFile
+-- ...
```

## Wire models

Models representing the Simple API use permissive handling for unknown keys.

The Simple Repository API is designed to allow additional fields to be added without breaking existing clients.

Compatag therefore ignores unknown wire fields while retaining strict schemas for its own domain models.

## Distribution classification

Modern wheel filenames are parsed with:

```
packaging.utils.parse_wheel_filename
```

Modern source distributions are parsed with:

```
packaging.utils.parse_sdist_filename
```

Recognized source distribution extensions are initially:

```
.tar.gz
.zip
```

Other or malformed historical files are preserved as:

```
kind = unknown
```

with a parse error rather than causing the entire project lookup to fail.

## Yanked files

Simple API yanked metadata is normalized into:

```
yanked: bool
yanked_reason: optional string
```

A yanked file remains part of the retrieved project data.

Selection policy belongs to the compatibility analyzer rather than the PyPI client.

## Errors

Compatag distinguishes:

```
InvalidProjectNameError
ProjectNotFoundError
PyPIRequestError
PyPIResponseError
```

This allows later layers to distinguish invalid input, a missing project, network failure, and malformed or unsupported repository data.

## API versioning

Compatag currently targets Simple Repository API major version 1 and has been tested through minor version 1.4.

A newer major version is rejected.

A newer minor version emits a warning and remains usable where the response can still be interpreted.

## Network policy

The initial client:

- uses HTTPS PyPI endpoints only;
- requests the JSON Simple API explicitly;
- identifies itself with a Compatag User-Agent;
- uses explicit connection and operation timeouts;
- does not automatically retry;
- does not download distribution files;
- does not execute package code.

Caching, bounded concurrency, and retry policy belong to later milestones.
