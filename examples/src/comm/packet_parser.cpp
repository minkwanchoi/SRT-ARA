// packet_parser.cpp - 통신 패킷 해석 (예외사유 표기법 예제)
#include <cstdint>
#include <cstring>
#include <ctime>
#include "packet_parser.hpp"

namespace comm {

bool PacketParser::parse(const std::uint8_t* data, std::size_t length, Packet& out)
{
    /*SRT-D-ID1-1START*/
    if (data == nullptr) {
        m_lastError = ErrorCode::NullInput;
        return false;
    }
    /*SRT-D-ID1-1END{
        @커버리지{분기}
        @미달성사유{입력되는 파라미터의 값의 NULL체크를 위한 구문으로 시스템에서 매우 예외적인
                    상황에서만 동작하는 방어 코드임. 호출부는 항상 수신 버퍼의 주소를 전달하므로
                    실제 장비에서는 해당 분기를 실행시킬 수 없음. 본 소스코드를 분석하여 시스템의
                    예외적인 상황에서도 동작하는 코드임을 확인함.}
        @요구사항{X-XXX-SFR-033 통신 예외처리}
    }*/
    if (length < kHeaderSize) {
        return false;
    }
    std::memcpy(&out.header, data, kHeaderSize);
    return decodeBody(data + kHeaderSize, length - kHeaderSize, out);
}

bool PacketParser::stamp(Packet& out) const
{
    const std::time_t now = std::time(nullptr);
    // SRT-S-C-ID1-1
    if (now == static_cast<std::time_t>(-1)) {
        return false;
    }
    out.receivedAt = now;
    return true;
}

bool PacketParser::verify(const Packet& in) const
{
    if (kChecksumEnabled) {     // SRT-S-C-ID1.2-1{@비고{체크섬 사용 구성}}
        return in.header.checksum == checksumOf(in);
    }
    return true;
}

// 메시지 종류별 분기는 모터 프로파일 선택(motor_ctrl.c)과 미달성 사유가 달라 같은 메트릭 ID 의 그룹 2로 쓴다.
/*SRT-S-M-ID1.2-1{
    @측정값{23}
    @미달성사유{통신 메시지 종류마다 길이 확인과 해석 함수를 고르는 분기 함수로, 메시지 종류가 늘어날
                때마다 case 가 하나씩 늘어남. 종류별 처리는 각 해석 함수로 이미 나뉘어 있어 이 함수를
                더 나누면 메시지 종류 표가 여러 곳으로 흩어짐.}
}*/
bool PacketParser::decodeBody(const std::uint8_t* body, std::size_t length, Packet& out)
{
    bool ok = true;
    switch (out.header.type) {
    case MsgType::Status:
        ok = (length >= 4u) && decodeStatus(body, out);
        break;
    case MsgType::Command:
        ok = (length >= 8u) && decodeCommand(body, out);
        break;
    default:                    /*SRT-D-ID1.2-1START*/
        ok = false;
        break;                  /*SRT-D-ID1.2-1END{
        @미달성사유{앞으로 더할 메시지 종류를 위해 둔 기본 처리(확장성을 고려한 코드)로, 지금 장비가 보내는
                    메시지는 모두 위의 case 에 해당하므로 시험으로 이 분기를 실행시킬 수 없음.
                    알 수 없는 종류를 받으면 해석하지 않고 실패로 돌려주는 것을 소스코드 분석으로 확인함.}
        @요구사항{X-XXX-SFR-035 메시지 종류 확장}
    }*/
    }
    return ok;
}

// SRT-S-M-ID1.2-1{@측정값{22}}
bool PacketParser::encodeBody(const Packet& in, std::uint8_t* body, std::size_t length) const
{
    bool ok = true;
    switch (in.header.type) {
    case MsgType::Status:
        ok = (length >= 4u) && encodeStatus(in, body);
        break;
    case MsgType::Command:
        ok = (length >= 8u) && encodeCommand(in, body);
        break;
    default:                    // SRT-D-ID1.2-1{@비고{송신 메시지 종류 확장}}
        ok = false;
        break;
    }
    return ok;
}

}  // namespace comm
