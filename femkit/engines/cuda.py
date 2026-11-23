"""CUDA helpers for device check programs, through NVIDIA's runtime bindings.

They report the device a check ran on and prove its data lived there. They
decide nothing about whether a check runs: that is the user's request
(envs.md § 5). The bindings are imported inside functions only.
"""

from __future__ import annotations


def _result(value, operation):
    status, *payload = value
    if int(status) != 0:
        raise RuntimeError(f"{operation} failed with CUDA status {int(status)}")
    return payload


def allocated_devices() -> list[dict]:
    from cuda.bindings import runtime

    result = runtime.cudaGetDeviceCount()
    # No driver or no device is an ordinary CPU machine; any other failure is an error,
    # not evidence that there is simply no GPU.
    if result[0] in (runtime.cudaError_t.cudaErrorNoDevice, runtime.cudaError_t.cudaErrorInsufficientDriver):
        return []
    count, = _result(result, "cudaGetDeviceCount")
    devices = []
    for ordinal in range(count):
        properties, = _result(runtime.cudaGetDeviceProperties(ordinal), "cudaGetDeviceProperties")
        bus, = _result(runtime.cudaDeviceGetPCIBusId(64, ordinal), "cudaDeviceGetPCIBusId")
        devices.append({
            "ordinal": ordinal,
            "name": bytes(properties.name).split(b"\0", 1)[0].decode("utf-8"),
            "pci_bus_id": bytes(bus).split(b"\0", 1)[0].decode("ascii"),
            "compute_capability": f"{properties.major}.{properties.minor}",
        })
    return devices


def current_device() -> dict:
    from cuda.bindings import runtime

    ordinal, = _result(runtime.cudaGetDevice(), "cudaGetDevice")
    devices = allocated_devices()
    if not 0 <= ordinal < len(devices):
        raise RuntimeError("the selected CUDA device is outside the visible allocation")
    return devices[ordinal]


def require_device_pointer(pointer: int) -> None:
    """Fail unless ``pointer`` is CUDA device (or managed) memory on the current device."""
    from cuda.bindings import runtime

    attributes, = _result(runtime.cudaPointerGetAttributes(pointer), "cudaPointerGetAttributes")
    if attributes.type not in (runtime.cudaMemoryType.cudaMemoryTypeDevice,
                               runtime.cudaMemoryType.cudaMemoryTypeManaged):
        raise RuntimeError("the vector is not in CUDA device memory")
    ordinal, = _result(runtime.cudaGetDevice(), "cudaGetDevice")
    if attributes.device != ordinal:
        raise RuntimeError("the vector belongs to a different CUDA device")
    _result(runtime.cudaDeviceSynchronize(), "cudaDeviceSynchronize")

