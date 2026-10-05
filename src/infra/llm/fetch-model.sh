#!/bin/sh
set -eu

models_dir="${LLM_MODELS_DIR:-/models}"
attempts="${LLM_GGUF_ATTEMPTS:-5}"
pause="${LLM_GGUF_RETRY_SECONDS:-15}"
target="$models_dir/$LLM_GGUF_FILE"
partial="$target.part"
verified="$target.sha256"

say() {
  echo "[llm-model] $*"
}

size_of() {
  stat -c %s "$1"
}

sha_of() {
  sha256sum < "$1" | cut -d ' ' -f 1
}

if [ -f "$target" ] && [ -f "$verified" ] \
  && [ "$(cat "$verified")" = "$LLM_GGUF_SHA256" ] \
  && [ "$(size_of "$target")" = "$LLM_GGUF_SIZE" ]; then
  say "$LLM_GGUF_FILE is in place and was verified before"
  exit 0
fi

rm -f "$verified"
if [ -f "$target" ]; then
  say "checking the $LLM_GGUF_FILE already in the models folder"
  if [ "$(size_of "$target")" = "$LLM_GGUF_SIZE" ] && [ "$(sha_of "$target")" = "$LLM_GGUF_SHA256" ]; then
    echo "$LLM_GGUF_SHA256" > "$verified"
    say "it has the expected SHA-256"
    exit 0
  fi
  say "it is not the expected file, so it is downloaded again"
  rm -f "$target"
fi

if [ -n "${HF_TOKEN:-}" ]; then
  set -- -H "Authorization: Bearer $HF_TOKEN"
else
  set --
fi

attempt=1
while :; do
  have=0
  if [ -f "$partial" ]; then
    have="$(size_of "$partial")"
  fi
  if [ "$have" -ge "$LLM_GGUF_SIZE" ]; then
    break
  fi
  say "downloading $LLM_GGUF_FILE ($LLM_GGUF_SIZE bytes, $have already here), attempt $attempt of $attempts"
  if curl -fL --connect-timeout 30 "$@" -C - -o "$partial" "$LLM_GGUF_URL"; then
    break
  fi
  if [ "$attempt" -ge "$attempts" ]; then
    say "ERROR: the download failed $attempts times. What arrived stays in $partial and the next start resumes from it."
    exit 1
  fi
  attempt=$((attempt + 1))
  sleep "$pause"
done

got="$(size_of "$partial")"
if [ "$got" != "$LLM_GGUF_SIZE" ]; then
  rm -f "$partial"
  say "ERROR: received $got bytes instead of $LLM_GGUF_SIZE. The file was deleted and the next start downloads it again."
  exit 1
fi

say "verifying the SHA-256"
actual="$(sha_of "$partial")"
if [ "$actual" != "$LLM_GGUF_SHA256" ]; then
  rm -f "$partial"
  say "ERROR: the SHA-256 is $actual, expected $LLM_GGUF_SHA256. The file was deleted and the next start downloads it again."
  exit 1
fi

mv "$partial" "$target"
echo "$LLM_GGUF_SHA256" > "$verified"
say "$LLM_GGUF_FILE verified and in place"
