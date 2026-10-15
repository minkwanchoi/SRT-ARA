/*
 * motor_ctrl.c - 구동 모터 제어 (예외사유 표기법 예제)
 */
#include <stdint.h>
#include <stddef.h>
#include <time.h>
#include "motor_ctrl.h"

#define MOTOR_REG_BASE   (0x40021000u)   /*SRT-S-C-ID2-2*/
#define MOTOR_ERR_TIME   (-1)
#define MOTOR_ERR_PARAM  (-2)

static uint32_t read_status(void)
{
    volatile uint32_t *reg = (volatile uint32_t *)MOTOR_REG_BASE;   /*SRT-S-C-ID2-1{
        @기준{MISRA-C:2012}
        @규칙{Rule 11.4}
        @FA내용{(규칙명: MISRA 문서를 보고 적는다)}
        @설명{메모리 맵 방식의 상태 레지스터에 접근하기 위해 데이터시트에 정의된 주소 상수를
              포인터로 변환하는 부분에서 Alarm 이 발생함.}
        @FA분석{하드웨어 레지스터는 고정 주소를 포인터로 변환하는 방법 외에 접근 수단이 없으며,
                주소 값은 MCU 데이터시트의 레지스터 맵과 일치함.}
        @결론{기능 구현을 위해 반드시 필요한 코드이며 주소 값의 정확성을 unit test 에서
              확인하였음. SW신뢰성 및 기능에 문제가 없음.}
        @Ref{OOO MCU 데이터시트 8.3절 Register Map}
        @첨부{evidence/regmap.png|근거자료: 레지스터 맵 발췌(예시)}
    }*/
    return *reg;
}

uint32_t motor_wait_mode(uint32_t mode)
{
    uint32_t u_res = 0u;
    do {                                    /*SRT-S-W-ID1-1START*/
        u_res = get_value(mode);
        delay_ms(1000u);
    } while (0u != u_res);                  /*SRT-S-W-ID1-1END{
        @위반 유형{Potential Unbounded Loop}
        @Ref.{CWE-835 Loop with Unreachable Exit Condition ('Infinite Loop')}
        @설명{위반이 발생한 부분은 디바이스에 전원이 인가되고, 사용자가 선택하는 모드를 수신하기
              위해 무한루프를 이용하여 대기하는 코드이다. 무한루프가 아니면 해당 값을 획득하지
              못하는 현상이 발생할 수 있음. 따라서 의도적인 무한루프이며 대체하거나 삭제할 수 없음.}
        @사유{상기사항은 개발자가 의도적으로 사용한 무한루프를 시험도구에서 검출하는 것이며
              동작상에 필요한 것이므로 False Alarm 이라고 판단함.}
        @결론{모드 수신 대기 기능은 integration test 에서 정상 동작을 확인하였음.}
        @첨부{srt_attach/SRT-S-W-ID1_diagram1.png|모드 수신 대기 흐름}
    }*/
    return u_res;
}

int32_t motor_log_time(time_t *out)
{
    time_t now = time(NULL);
    if (now == (time_t)-1) {                /*SRT-S-C-ID1-1START*/
        return MOTOR_ERR_TIME;
    }                                       /*SRT-S-C-ID1-1END{
        @기준{MISRA-C:2012}
        @규칙{Rule 14.3}
        @FA내용{(규칙명: MISRA 문서를 보고 적는다)}
        @설명{time()함수에서 현재 시각을 가져오는 부분에서 비정상적인 리턴이 넘어올 경우 예외
              처리를 위해 ERROR값 여부를 판정하는 조건문에서 Alarm이 발생하였으나 OS 제조사에서
              제공하는 Reference 확인 결과 ERROR는 가능한 리턴값임.}
        @FA분석{time()함수에서 시스템의 현재 시각을 가져오는 부분에서 정상적으로 시각을 가져오지
                못하는 상황에 대한 예외 처리를 하였으나 제조사 Reference를 참고하여 변수의 타입을
                설정하였음에도 SW신뢰성 시험 도구가 오류로 검출한 내용임.}
        @결론{본 내용은 OS사에서 제공하는 함수를 사용하였으며, 해당 리턴값을 준수하였으므로 기능이
              정상적으로 동작하는 것을 unit test 및 integration test에서 확인하였음.
              SW신뢰성 및 기능에 문제가 없음.}
    }*/
    *out = now;
    return 0;
}

int32_t motor_periodic_check(void)
{
    time_t stamp = time(NULL);
    if (stamp == (time_t)-1) {              /*SRT-S-C-ID1-1{@비고{주기 점검 경로}}*/
        return MOTOR_ERR_TIME;
    }
    return (int32_t)(read_status() & 0xFFu);
}

/*SRT-S-M-ID1-1{
    @메트릭{Cyclomatic Complexity}
    @제한값{20 이하}
    @측정값{21}
    @미달성사유{구동 프로파일 선택 알고리즘 처리 함수로, 운용 모드와 부하/온도 구간의 조합에 따라
                프로파일을 결정하기 위해 다중 switch/if문을 사용하고 있음. 함수를 분리하면 구간
                판정 조건이 여러 함수로 흩어져 오히려 가독성과 검증성이 떨어짐.}
}*/
int32_t motor_select_profile(uint32_t mode, int32_t load, int32_t temp)
{
    int32_t profile = 0;
    switch (mode) {
    case 0u:
        profile = (load > 80) ? 3 : ((load > 40) ? 2 : 1);
        break;
    case 1u:
        if ((temp > 85) || (temp < -30)) {
            profile = 0;
        } else if (load > 60) {
            profile = 4;
        } else {
            profile = 2;
        }
        break;
    case 2u:
        profile = (temp > 70) ? 1 : 5;
        break;
    default:
        profile = MOTOR_ERR_PARAM;
        break;
    }
    return profile;
}
