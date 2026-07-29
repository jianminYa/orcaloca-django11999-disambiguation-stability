import os
import random
import time
from typing import Dict, Union

import anthropic
import openai
import tiktoken


OPENAI_BASE_URL_KEYS = (
    "OPENAI_BASE_URL",
    "BASE_URL",
    "API_BASE_URL",
    "OPENAI_API_BASE",
)


def get_openai_base_url():
    for key in OPENAI_BASE_URL_KEYS:
        value = os.environ.get(key)
        if value:
            return value
    return None


def sleep_before_retry(retries, logger, reason):
    delay = min(60, (2 ** min(retries, 5)) + random.uniform(0, 1))
    logger.info(f"{reason}. Waiting {delay:.1f}s before retry {retries + 1}.")
    time.sleep(delay)


def num_tokens_from_messages(message, model="gpt-3.5-turbo-0301"):
    """Returns the number of tokens used by a list of messages."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    if isinstance(message, list):
        # use last message.
        num_tokens = len(encoding.encode(message[0]["content"]))
    else:
        num_tokens = len(encoding.encode(message))
    return num_tokens


def create_chatgpt_config(
    message: Union[str, list],
    max_tokens: int,
    temperature: float = 1,
    batch_size: int = 1,
    system_message: str = "You are a helpful assistant.",
    model: str = "gpt-3.5-turbo",
) -> Dict:
    if isinstance(message, list):
        config = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "n": batch_size,
            "messages": [{"role": "system", "content": system_message}] + message,
        }
    else:
        config = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "n": batch_size,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": message},
            ],
        }
    return config


def handler(signum, frame):
    # swallow signum and frame
    raise Exception("end of time")


def request_chatgpt_engine(config, logger, base_url=None, max_retries=40, timeout=100):
    ret = None
    retries = 0

    client = openai.OpenAI(
        base_url=base_url or get_openai_base_url(),
        timeout=timeout,
        max_retries=0,
    )

    while ret is None and retries < max_retries:
        try:
            # Attempt to get the completion
            logger.info("Creating API request")

            ret = client.chat.completions.create(**config)

        except openai.OpenAIError as e:
            if isinstance(e, openai.BadRequestError):
                logger.info("Request invalid")
                print(e)
                logger.info(e)
                raise Exception("Invalid API Request")
            elif isinstance(e, openai.APIStatusError):
                status_code = getattr(e, "status_code", None)
                if status_code and (status_code >= 500 or status_code in {408, 409, 429}):
                    logger.info(e)
                    sleep_before_retry(retries, logger, f"Retryable API status {status_code}")
                else:
                    logger.info("Non-retryable API status")
                    print(e)
                    logger.info(e)
                    raise
            elif isinstance(e, openai.RateLimitError):
                print("Rate limit exceeded. Waiting...")
                logger.info("Rate limit exceeded. Waiting...")
                logger.info(e)
                sleep_before_retry(retries, logger, "Rate limit exceeded")
            elif isinstance(e, (openai.APIConnectionError, openai.APITimeoutError)):
                logger.info("API connection or timeout error. Waiting...")
                logger.info(e)
                sleep_before_retry(retries, logger, "API connection or timeout error")
            else:
                logger.info("Unknown error. Waiting...")
                logger.info(e)
                sleep_before_retry(retries, logger, "Unknown OpenAI API error")

        retries += 1

    if ret is None:
        raise RuntimeError(f"OpenAI-compatible request failed after {max_retries} retries")

    logger.info(f"API response {ret}")
    return ret


def create_anthropic_config(
    message: str,
    max_tokens: int,
    temperature: float = 1,
    batch_size: int = 1,
    system_message: str = "You are a helpful assistant.",
    model: str = "claude-2.1",
    tools: list = None,
) -> Dict:
    if isinstance(message, list):
        config = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": message,
        }
    else:
        config = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": message}]},
            ],
        }

    if tools:
        config["tools"] = tools

    return config


def request_anthropic_engine(
    config, logger, max_retries=40, timeout=500, prompt_cache=False
):
    ret = None
    retries = 0
    max_retries = int(os.environ.get("AGENTLESS_ANTHROPIC_MAX_RETRIES", max_retries))
    timeout = float(os.environ.get("AGENTLESS_ANTHROPIC_TIMEOUT", timeout))

    client_kwargs = {
        "timeout": timeout,
        "max_retries": 0,
    }
    if os.environ.get("ANTHROPIC_BASE_URL"):
        client_kwargs["base_url"] = os.environ["ANTHROPIC_BASE_URL"]
    client = anthropic.Anthropic(**client_kwargs)

    while ret is None and retries < max_retries:
        try:
            start_time = time.time()
            if prompt_cache:
                # following best practice to cache mainly the reused content at the beginning
                # this includes any tools, system messages (which is already handled since we try to cache the first message)
                config["messages"][0]["content"][0]["cache_control"] = {
                    "type": "ephemeral"
                }
                ret = client.messages.create(**config)
            else:
                ret = client.messages.create(**config)
        except Exception as e:
            logger.error("Unknown error. Waiting...", exc_info=True)
            # Check if the timeout has been exceeded
            if time.time() - start_time >= timeout:
                logger.warning("Request timed out. Retrying...")
            else:
                logger.warning("Retrying after an unknown error...")
            sleep_before_retry(retries, logger, "Anthropic API error")
        retries += 1

    if ret is None:
        raise RuntimeError(f"Anthropic request failed after {max_retries} retries")

    return ret
