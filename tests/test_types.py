from autumn.core.types import InputType, MissionRoute, Protocol, Role, Message


def test_protocol_values():
    assert Protocol.OPENAI == "openai"
    assert Protocol.ANTHROPIC == "anthropic"


def test_input_type_values():
    assert InputType.TASK == "task"
    assert InputType.MISSION == "mission"


def test_mission_route_values():
    assert MissionRoute.DIRECT == "direct"
    assert MissionRoute.CONVERT == "convert"


def test_message_creation():
    msg = Message(role=Role.USER, content="Hello")
    assert msg.role == Role.USER
    assert msg.content == "Hello"
