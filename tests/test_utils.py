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
