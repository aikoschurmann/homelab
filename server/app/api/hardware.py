from flask import Blueprint, jsonify

from app.services import hardware

hardware_bp = Blueprint('hardware', __name__)


@hardware_bp.route('', methods=['GET'])
def this_server():
    return jsonify({"status": "success", "data": {**hardware.local(), "warn": hardware.TEMP_WARN}})


@hardware_bp.route('/<hid>', methods=['GET'])
def of_host(hid):
    from app.api.hosts import hardware_of
    return jsonify({"status": "success", "data": {**(hardware_of(hid) or {}), "warn": hardware.TEMP_WARN}})
