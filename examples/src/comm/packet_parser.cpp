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

// SRT-S-M-ID1-1{@측정값{23}}
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
    default:
        ok = false;
        break;
    }
    return ok;
}

}  // namespace comm
