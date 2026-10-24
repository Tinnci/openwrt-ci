// SPDX-License-Identifier: GPL-2.0-only
/* Linux v6.12.108 excerpts; unrelated card discovery/feature setup omitted.
 * This fixture is not a replacement for compiling the complete kernel.
 */

/*
 * Activate High Speed, HS200 or HS400ES mode if supported.
 */
static int mmc_select_timing(struct mmc_card *card)
{
	int err = 0;

	if (!mmc_can_ext_csd(card))
		goto bus_speed;

	if (card->mmc_avail_type & EXT_CSD_CARD_TYPE_HS400ES) {
		err = mmc_select_hs400es(card);
		goto out;
	}

	if (card->mmc_avail_type & EXT_CSD_CARD_TYPE_HS200) {
		err = mmc_select_hs200(card);
		if (err == -EBADMSG)
			card->mmc_avail_type &= ~EXT_CSD_CARD_TYPE_HS200;
		else
			goto out;
	}

	if (card->mmc_avail_type & EXT_CSD_CARD_TYPE_HS)
		err = mmc_select_hs(card);

out:
	if (err && err != -EBADMSG)
		return err;

bus_speed:
	/*
	 * Set the bus speed to the selected bus timing.
	 * If timing is not selected, backward compatible is the default.
	 */
	mmc_set_bus_speed(card);
	return 0;
}

/*
 * Handle the detection and initialisation of a card.
 *
 * In the case of a resume, "oldcard" will contain the card
 * we're trying to reinitialise.
 */
static int mmc_init_card(struct mmc_host *host, u32 ocr,
	struct mmc_card *oldcard)
{
	struct mmc_card *card;
	int err;
	u32 cid[4];
	u32 rocr;

	WARN_ON(!host->claimed);

	/* Set correct bus mode for MMC before attempting init */
	if (!mmc_host_is_spi(host))
		mmc_set_bus_mode(host, MMC_BUSMODE_OPENDRAIN);

	/* TEST_DISCOVERY: original discovery and EXT_CSD parsing omitted. */

	/*
	 * Select timing interface
	 */
	err = mmc_select_timing(card);
	if (err)
		goto free_card;

	if (mmc_card_hs200(card)) {
		host->doing_init_tune = 1;

		err = mmc_hs200_tuning(card);
		if (!err)
			err = mmc_select_hs400(card);

		host->doing_init_tune = 0;

		if (err)
			goto free_card;
	} else if (mmc_card_hs400es(card)) {
		if (host->ops->execute_hs400_tuning) {
			err = host->ops->execute_hs400_tuning(host, card);
			if (err)
				goto free_card;
		}
	} else {
		/* Select the desired bus width optionally */
		err = mmc_select_bus_width(card);
		if (err > 0 && mmc_card_hs(card)) {
			err = mmc_select_hs_ddr(card);
			if (err)
				goto free_card;
		}
	}

	/* TEST_FEATURES: original non-timing feature setup omitted. */

	if (!oldcard)
		host->card = card;

	return 0;

free_card:
	if (!oldcard)
		mmc_remove_card(card);
err:
	return err;
}

static int mmc_can_sleep(struct mmc_card *card)
{
	return card->ext_csd.rev >= 3;
}
