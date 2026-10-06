# Validation and error handling

Validation and error handling must be enforced at every system boundary. The frontend validates user input for usability, the API validates every request for correctness, and service-level checks reject malformed or oversized payloads before they reach business logic. The system must never trust the client, and user-facing errors must be clear, actionable, and consistent.

## General principles

For this project, we didn't used error messages to reach an esthetic goal but to enforce a real secure aspect to makes sure that the user can trust our solution at each step of the utilisation. 

Here are several principles that we tried to apply :
  - Never trusting the client's identity, always checking the token attributed during the login process.
  - Validate at every boundary.
  - Fail with clear messages to let an opportunity to the user to fix the problem.
  - Keep validation consistent across frontend and backend.
  - Log operational errors, but never log secrets or content.

## Where do we validate what ?

| Layer | What is validated | Method | Typical status |
| --- | --- | --- | --- |
| **UI** | required fields, password strength, matching fields | Zod | client-side only |
| **API** | request body, auth, path params, IDs | Pydantic / FastAPI | 400 / 401 / 404 / 422 |
| **File upload** | file type, size, format | manual checks + service logic | 413 / 422 |
| **Queue / services** | agent payloads, message structure | Pydantic models | internal validation |
| **Installer** | Python version, Docker, ports, disk | preflight checks | clear install error |

### UI

For the UI part, a small example would be with this small typescript function:

```typescript
export const baseRegisterSchema = z
  .object({
    username: z
      .string()
      .min(1, 'Username is required'),
    password: z
      .string()
      .min(10, 'Password must be at least 10 characters')
      .regex(
        passwordRegex,
        'Password must include uppercase, lowercase, number, and special character'
      ),
    confirmPassword: z.string().min(1, 'Please confirm your password'),
  });

```

Using the Zod method, we always ensure that the user will set up a password following established rules concerning the lenghth of it that is 10 characters at least.

Following this Zod process, we also ensure that the password that the user will enter is matching : 

```typescript
export const registerSchema = baseRegisterSchema.refine(
  (data) => data.password === data.confirmPassword,
  { message: "Passwords don't match", path: ['confirmPassword'] }
);
```

### API

Still on the thematic of the password modification as example, we ensured to have the clearest and detailled communication in our communication's process throught the differents API.

```python
class CreateUserRequest(BaseModel):
    """User registration payload. Password is bcrypt-hashed before storage."""

    username: str
    password: str

    @field_validator("password")
    @classmethod
    def password_policy(cls, value: str) -> str:
        return check_password_policy(value)
```

With this "field_validator", each information is checked before the final autorisation's sending. Here the information checked will be the password. Following the answer of the program, it will allows us to deliver the clearest error code : 400 / 401 / 404 / 422. The program here will reject the password entered if it doesn't contains an uppercase letter, a lowercase letter, a digit or a special character.

### File Upload

In this part, it's clear that to stay efficient, we can't elaborate advanced parameters. But the goal will be to ensure for example that the format and the size respect the rules.

```python
async def upload_file_to_text(type: str, doc_id: str, file: UploadFile = File(...)):
    """
    Upload a single file, convert it to text, analyze, and store it.

    Args:
        type: File type ('pdf', 'docx', 'image').
        doc_id: Pre-assigned document ID.
        file: The file to upload.

    Returns:
        Filename, storage path, extracted text, and auto-analysis.
    """
    path = await save_file(file, type)

    if type == "pdf":
        text = await pdf_to_text(path)
    elif type == "docx":
        text = await docx_to_text(path)
    elif type == "image":
        text = await image_pdf_to_text(path)
    else:
        raise HTTPException(status_code=400, detail="Invalid file type")

    auto_analysis = await asyncio.to_thread(
        _content_analyzer.analyze,
        text,
        file.filename,
    )

    await store_file(
        DocumentModel(
            id=doc_id,
            title=file.filename,
            content=text,
            size=os.path.getsize(path) if os.path.exists(path) else 0,
        ),
        auto_analysis=auto_analysis,
    )

    return {
        "filename": file.filename,
        "stored_at": path,
        "text": text,
        "auto_analysis": auto_analysis,
    }
```

Here the goal will be to check if the file uploaded corresponds to one of these format : pdf, docx or if it's an image. Depending the answer, send an error code 400 if the file uploaded doesn't follows the rules established.

### Queue / Service

An other type of checking very important will concerns the internal validtions. These validations will operate by checking the format of each information that will be sent to our API. To do this we will use Pydantic models.

```python
class TaskForm(BaseModel):
    """Task creation payload.

    The dispatcher honours ``mode``:

    - ``auto`` (default) — LLM router picks the agent; ``agent_id`` is ignored.
    - ``specific_agent`` — required ``agent_id`` is used verbatim; the dispatch
      will queue-on-busy if the worker is currently offline.
    - ``any_with_skill`` — first registered agent whose skills include
      ``skills_required[0]`` is selected (live agents preferred, seeded ones
      fall back).

    ``agent_id`` and ``mode`` are optional so older clients keep working.
    ``attached_files`` and ``inline_files`` are forwarded to the worker as a
    unified ``files`` array; both default to empty for backward compatibility.
    """

    demand: str
    conversation_id: int | None = None
    skills_required: list[str]
    agent_id: str | None = None
    mode: TaskMode | None = None
    attached_files: list[KnowledgeStoreFileRef] = []
    inline_files: list[InlineFile] = []
```

We will check the topology of each information, for example if the request sent follow the correct structure, and being sure that for example if a string is waiting, the user will furnish it. If the user made a mistake by sending the wrong one, a Pydantic error will be sent.

### Installer

The last type of error will be related to the installation process. For this part, we will use preflight checks. In this part, it will be important to check packages's versions. On this way, our programm will examine the environment before compiling it.

```python
def check_python(log: Log) -> None:
    log.step("1/6  Python")
    got = sys.version_info[:3]
    if got < MIN_PYTHON:
        raise InstallError(
            EXIT_PYTHON_TOO_OLD,
            f"Python {'.'.join(map(str, MIN_PYTHON))} or newer is required.",
            f"This interpreter is {'.'.join(map(str, got))} at {sys.executable}.",
            "Install Python 3.11+ from https://www.python.org/downloads/\n"
            "On Windows, tick 'Add python.exe to PATH' in the installer.\n"
            "Then run the START-HERE launcher again.",
        )
    log.ok(f"Python {'.'.join(map(str, got))}")
  ```

In this program, the goal will be to check the python version. If everything goes well, the program will just continue to be executed. But if something goes wrong, a clear install error will appears and the program will be closed automatically with the instruction "EXIT_PYTHON_TOO_OLD".

## Error Format

Depending where an error will happen and what goes wrong with the program, we will adopt a different error format to adapt to the type of libraries that we are currently using but also adding clearance as much as possible in the error message to let the opportunity to the user to fix the problem easily and having a better understanding of the context.

For example, with an API a simple error message will appear :

```json
{
  "detail": "Invalid file type. Accepted formats: PDF, DOCX, PNG, JPG."
}
```

But for a pydantic error, the format of the error message will have to chance a bit :
```json
{
  "detail": [
    {
      "loc": ["body", "demand"],
      "msg": "Field required",
      "type": "missing"
    }
  ]
}
```

## Error Code

To give as much clearance as possible but also to sort a bit errors that can happen, we used specific error code depending the problem encountered : 

| Code | Usage | Exemple |
| --- | --- | --- |
| 400 | Invalid request | Unknown file extension |
| 401 | Invalid Authentication or missing | JWT Token missing |
| 403 | User logged but not allowed | A standard user account tryes to do an admin's action |
| 404 | Ressource not found | Conversation or task unknown |
| 409 | Conflict | An agent or a file already has this name |
| 413 | Payload too large | File crossed the size's limit |
| 422 | Invalid value or structure | Mandatory field missing, wrong type |
| 500 | Internal error unexpected | Failure not expected during the execution |

```python
except Exception as e:
    logger.error(
        f"Task processing failed via HTTP: task_id={task.task_id}, error={str(e)}",
        exc_info=True
    )
    raise
```

In our algorithm, each request will be personalized depending the problem encountered. But the most important thing to remember is that after this error code is that we will try to go to the source of the problem to present a clear error message instead of just the technical detail of an exception. The program will always try to minimize the technical level of the message to be sure that everyone will be able to fix everything. We never put at disposition of the user the message that we received exactly with for example :
```text
str(e)
```

## User messages

For us, a good message have to be short but clear and give a maximum of useful details to correct the problem. 

Here is a good error message :

```text
The uploaded file is too large. Maximum allowed size: 10 MB.
```
```text
A document named "report.pdf" already exists. Rename the file and try again.
```
If an action of the user is required, it's always important to mention it.

In comparison, this an example of very bad error message: 
```text
Something went wrong.
```

## Correlation ID and logs

As we put an importance on having a clear error message, it's important to track all of the important informations that will describe the situation to be able to track the error but also reproduce it.

```text
Request failed
method=POST
path=/task
status=500
correlation_id=8c4f...
```

Passwords, JWT tokens, API keys and document contents must never be logged. We have a clear respect of all of the personal informations. To understand from which user the error message provide, each request receives a correlation ID. It may be provided by the client through X-Request-ID or X-Correlation-ID, or generated by the server. It helps the team trace the request and investigate the error. It does not identify the user and must never be used as a credential.

## Checklist PR

Here are the different messages that you could encouter during your experience.

- [ ] Request body validated with Pydantic or equivalent
- [ ] Authentication and authorization checked
- [ ] Invalid input returns 422
- [ ] Missing authentication returns 401
- [ ] Forbidden action returns 403
- [ ] Missing resource returns 404
- [ ] Conflict and size-limit cases are handled
- [ ] Error message is actionable
- [ ] No password, token or document content is logged
- [ ] Error cases have automated tests
