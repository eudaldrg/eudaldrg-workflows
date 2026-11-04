// Proves the test wiring works end to end: GoogleTest fetched, linked and discovered by ctest.
// Replace it with real tests; keep at least one test so ctest's no-tests check stays meaningful.
#include <gtest/gtest.h>

namespace {

TEST(SmokeTest, TestFrameworkRuns) {
    EXPECT_EQ(1 + 1, 2);
}

}  // namespace
