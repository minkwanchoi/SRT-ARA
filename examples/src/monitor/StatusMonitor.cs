using System;
using System.Collections.Generic;

namespace Monitor
{
    /// <summary>장비 상태 감시 (예외사유 표기법 예제)</summary>
    public class StatusMonitor
    {
        private readonly Dictionary<int, string> _names = new Dictionary<int, string>();

        public string Describe(int deviceId)
        {
            string name;
            _names.TryGetValue(deviceId, out name);
            /*SRT-S-W-ID2-1START*/
            if (name == null)
            {
                name = "UNKNOWN";
            }
            return name.Trim();
            /*SRT-S-W-ID2-1END{
                @취약점{NULL Pointer Dereference}
                @Ref{CWE-476 NULL Pointer Dereference}
                @FA내용{NULL 이 될 수 있는 참조를 역참조해서는 안 된다.}
                @설명{TryGetValue() 가 실패하면 name 이 null 이 되므로 도구가 name.Trim() 을
                      NULL 역참조로 검출함.}
                @FA분석{역참조 직전의 조건문에서 null 인 경우 "UNKNOWN" 을 대입하므로 name.Trim()
                        시점에는 null 이 될 수 없음. 도구가 직전 대입을 추적하지 못한 오검출임.}
                @결론{미등록 장비 ID 에 대한 동작을 unit test 에서 확인하였음. SW신뢰성 및 기능에
                      문제가 없음.}
            }*/
        }

        public bool Register(int deviceId, string name)
        {
            // SRT-D-ID1-1{@비고{장비 이름 NULL 방어 코드}}
            if (name == null)
            {
                return false;
            }
            _names[deviceId] = name;
            return true;
        }
    }
}
