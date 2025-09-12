import pytest
import requests
import responses

from qibo_client import exceptions, utils


def test_check_json_response_has_keys():
    """Check response body contains the keys"""
    keys = ["key1", "key2"]
    json_data = {"key1": 0, "key2": 1}
    utils.check_json_response_has_keys(json_data, keys)


def test_check_json_response_has_missing_keys():
    """Check response body contains the keys"""
    keys = ["key1", "key2"]
    response_json = {"key1": 0}
    with pytest.raises(exceptions.MalformedResponseError) as err:
        utils.check_json_response_has_keys(response_json, keys)

    expected_message = "The server response is missing the following keys: key2"
    assert str(err.value) == expected_message


@responses.activate
def test_get_request_with_200_output():
    endpoint = "http://fake.endpoint.com/api"
    params = {"testParam": "fake"}
    timeout = 10
    response_json = {"detail": "the output"}
    keys_to_check = ["detail"]

    responses.add(responses.GET, endpoint, json=response_json, status=200)

    response = utils.QiboApiRequest.get(
        endpoint, params=params, timeout=timeout, keys_to_check=keys_to_check
    )

    assert isinstance(response, requests.Response)
    assert response.json() == response_json


@responses.activate
def test_get_request_with_404_error():
    endpoint = "http://fake.endpoint.com/api"
    status_code = 404
    message = "the output"

    responses.add(responses.GET, endpoint, json={"detail": message}, status=status_code)

    with pytest.raises(exceptions.JobApiError) as err:
        utils.QiboApiRequest.get(endpoint)

    expected_message = f"\033[91m[{status_code} Error] {message}\033[0m"
    assert str(err.value) == expected_message


@responses.activate
def test_post_request_with_200_output():
    endpoint = "http://fake.endpoint.com/api"
    body = {"input": "body"}
    timeout = 10
    keys_to_check = ["detail"]
    response_json = {"detail": "the output"}

    responses.add(responses.POST, endpoint, json=response_json, status=200)

    response = utils.QiboApiRequest.post(
        endpoint, json=body, timeout=timeout, keys_to_check=keys_to_check
    )

    assert isinstance(response, requests.Response)
    assert response.json() == {"detail": "the output"}


@responses.activate
def test_post_request_with_404_error():
    endpoint = "http://fake.endpoint.com/api"
    status_code = 404
    message = "the output"

    responses.add(
        responses.POST, endpoint, json={"detail": message}, status=status_code
    )

    with pytest.raises(exceptions.JobApiError) as err:
        utils.QiboApiRequest.post(endpoint)

    expected_message = f"\033[91m[{status_code} Error] {message}\033[0m"
    assert str(err.value) == expected_message


@responses.activate
def test_request_with_invalid_json_response():
    """Test handling of invalid JSON in an error response."""
    endpoint = "http://fake.endpoint.com/api"
    responses.add(
        responses.GET,
        endpoint,
        body="invalid json",
        status=400,
        content_type="application/json",
    )

    with pytest.raises(exceptions.JobApiError) as err:
        utils.QiboApiRequest.get(endpoint)

    assert err.value.status_code == 400
    assert "invalid json" in str(err.value)


@responses.activate
def test_request_with_json_error_message():
    """Test handling of error messages in JSON response."""
    endpoint = "http://fake.endpoint.com/api"
    error_detail = "Something went wrong"
    responses.add(responses.GET, endpoint, json={"error": error_detail}, status=400)

    with pytest.raises(exceptions.JobApiError) as err:
        utils.QiboApiRequest.get(endpoint)

    assert error_detail in str(err.value)
    assert "[400 Error]" in str(err.value)


@responses.activate
def test_request_with_connection_error():
    """Test handling of connection errors."""
    endpoint = "http://fake.endpoint.com/api"

    responses.add(
        responses.GET,
        endpoint,
        body=requests.exceptions.ConnectionError("Connection refused"),
    )

    with pytest.raises(exceptions.JobApiError) as err:
        utils.QiboApiRequest.get(endpoint)

    # Current implementation returns the exception’s string if it’s non-empty
    assert err.value.status_code == 0
    assert "Connection refused" in str(err.value)


@responses.activate
def test_request_with_json_string_error():
    """Test handling of stringified JSON in error message."""
    endpoint = "http://fake.endpoint.com/api"
    error_detail = "Something went wrong"
    responses.add(
        responses.GET,
        endpoint,
        body=f'{{"error": "{error_detail}"}}',  # Stringified JSON
        status=400,
        content_type="text/plain",
    )

    with pytest.raises(exceptions.JobApiError) as err:
        utils.QiboApiRequest.get(endpoint)

    assert error_detail in str(err.value)


@responses.activate
def test_error_cleanup_parses_json_string_list():
    endpoint = "http://fake.endpoint.com/api"

    # Make payload a dict so payload.get(...) works.
    # The "error" field contains a string that looks like JSON list -> triggers cleanup.
    responses.add(
        responses.GET,
        endpoint,
        json={"error": '["e1", "e2"]'},
        status=422,
        content_type="application/json",
    )

    with pytest.raises(exceptions.JobApiError) as err:
        utils.QiboApiRequest.get(endpoint)

    assert err.value.status_code == 422
    # After cleanup, the code does json.loads(...) -> list -> str(list)
    assert "['e1', 'e2']" in str(err.value)


@responses.activate
def test_request_exception_httpsconnectionpool_normalized_message():
    endpoint = "http://fake.endpoint.com/api"

    responses.add(
        responses.GET,
        endpoint,
        body=requests.exceptions.ConnectionError(
            "HTTPSConnectionPool(host='fake.endpoint.com', port=443): Max retries exceeded"
        ),
    )

    with pytest.raises(exceptions.JobApiError) as err:
        utils.QiboApiRequest.get(endpoint)

    assert err.value.status_code == 0
    assert "Could not connect to the server" in str(err.value)


@responses.activate
def test_request_exception_empty_message_normalized():
    endpoint = "http://fake.endpoint.com/api"

    # Explicitly raise a RequestException with an empty message
    responses.add(
        responses.GET,
        endpoint,
        body=requests.exceptions.RequestException(""),
    )

    with pytest.raises(exceptions.JobApiError) as err:
        utils.QiboApiRequest.get(endpoint)

    assert err.value.status_code == 0
    assert "Could not connect to the server" in str(err.value)


@responses.activate
def test_error_cleanup_json_loads_raises_valueerror():
    """Cleanup branch: error_message starts with '{' but is invalid JSON → json.loads raises → except path."""
    endpoint = "http://fake.endpoint.com/api"

    # payload["error"] is a string that LOOKS like JSON but is invalid (missing closing brace)
    invalid_json_like_string = '{"not valid json": 123'

    responses.add(
        responses.GET,
        endpoint,
        json={"error": invalid_json_like_string},
        status=400,
        content_type="application/json",
    )

    with pytest.raises(exceptions.JobApiError) as err:
        utils.QiboApiRequest.get(endpoint)

    # We should keep the original string since cleanup except-path 'pass'es.
    assert err.value.status_code == 400
    assert invalid_json_like_string in str(err.value)
