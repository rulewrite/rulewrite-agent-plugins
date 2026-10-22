---
name: environments
description: 카카오 선물하기 환경(샌드박스·베타·로컬 개발) 접속 정보와 테스트 계정을 다룬다. 샌박/베타 접속·검증 요청, 테스트 계정 로그인, 애조로(fedev) 도메인 확인, "어느 주소로 접속하지" 류 질문, 접속 정보·계정 기록 요청 시 반드시 사용. 브라우저로 선물하기 환경을 여는 모든 작업은 시작 전에 이 스킬로 접속 정보를 확인한다.
---

# environments

## 환경 URL

- 샌드박스: https://sandbox-gift.kakao.com
- 베타: https://beta-gift.kakao.com
- 로컬 개발(애조로 → 이 장비의 개발 서버, 기본 :8080)
  - 회사: 환경변수 `KAKAO_GIFT_DEV_DOMAIN_OFFICE`
    - Claude Code: ${user_config.dev_domain_office}
  - 집: 환경변수 `KAKAO_GIFT_DEV_DOMAIN_HOME`
    - Claude Code: ${user_config.dev_domain_home}
  - 접속이 안 되면(504 등) 애조로(https://azr.9rum.cc) UBalance 레코드의 IP가 낡았을 가능성부터 본다.

## 테스트 계정

- 샌드박스 id: 환경변수 `KAKAO_GIFT_SANDBOX_ACCOUNT_ID`
  - Claude Code: ${user_config.sandbox_account_id}
- 비밀번호: 사용 직전에만 환경변수 `KAKAO_GIFT_SANDBOX_PASSWORD`에서 읽는다.

## 값이 비어 있으면

- 도메인·id: 위 환경변수를 에이전트 실행 환경에 설정하도록 안내한다.
  - Claude Code: 플러그인 설정에서 채우도록 안내한다.
- 비밀번호: 대화로 일회성으로 받지 않고, 에이전트 환경과 버전에 맞는 보안 방식으로 설정하도록 안내한다.

## 로그인 자동화 시 주의

- 비밀번호를 터미널 출력·대화 응답·스크린샷에 남기지 않는다. 자동화 도구에 값을 넘기며 로컬 세션 기록에 남는 것은 감수한다.
- 2단계 인증 등 사람 개입이 필요한 단계는 사용자에게 넘긴다.
